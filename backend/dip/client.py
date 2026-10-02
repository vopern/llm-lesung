"""DIP API client (Contract 2).

Talks to the Bundestag DIP search API to list Gesetzentwurf and
Beschlussempfehlung metadata and fetch per-Vorgang status. All requests are
sequential, carry the referer-locked auth headers, and use a 30s timeout. Non-200 responses raise ``RuntimeError``.
"""

import httpx

from backend import config

_TIMEOUT = 30.0

# DIP drucksachetypen the pipeline ingests.
GESETZENTWURF_TYP = "Gesetzentwurf"
BESCHLUSSEMPFEHLUNG_TYP = "Beschlussempfehlung und Bericht"


def _get(client: httpx.Client, path: str, params: dict | None = None) -> dict:
    """GET a DIP endpoint and return parsed JSON, raising on non-200."""
    resp = client.get(path, params=params)
    if resp.status_code != 200:
        raise RuntimeError(
            f"DIP request failed: GET {resp.request.url} -> "
            f"{resp.status_code} {resp.text[:200]!r}"
        )
    return resp.json()


def _fetch_drucksachen(
    drucksachetyp: str, limit: int | None = None, wahlperiode: int = 21
) -> list[dict]:
    """Fetch all Drucksachen of one ``drucksachetyp`` for a Wahlperiode.

    Uses cursor pagination: the ``cursor`` from each response is passed back
    until it stops changing or the ``documents`` array comes back empty.
    Stops early once ``limit`` documents have been collected.
    """
    params = {
        "f.drucksachetyp": drucksachetyp,
        "f.zuordnung": "BT",
        "f.wahlperiode": wahlperiode,
    }
    documents: list[dict] = []
    cursor: str | None = None
    with httpx.Client(
        base_url=config.DIP_BASE_URL,
        headers=config.dip_headers(),
        timeout=_TIMEOUT,
    ) as client:
        while True:
            call_params = dict(params)
            if cursor is not None:
                call_params["cursor"] = cursor
            data = _get(client, "/drucksache", call_params)
            batch = data.get("documents") or []
            if not batch:
                break
            documents.extend(batch)
            if limit is not None and len(documents) >= limit:
                documents = documents[:limit]
                break
            next_cursor = data.get("cursor")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
    return documents


def fetch_gesetzentwuerfe(limit: int | None = None, wahlperiode: int = 21) -> list[dict]:
    """Fetch all Gesetzentwurf Drucksachen for a Wahlperiode."""
    return _fetch_drucksachen(GESETZENTWURF_TYP, limit=limit, wahlperiode=wahlperiode)


def fetch_drucksache(document_id: str) -> dict:
    """Fetch one Drucksache by id (the detail response, untruncated)."""
    with httpx.Client(
        base_url=config.DIP_BASE_URL,
        headers=config.dip_headers(),
        timeout=_TIMEOUT,
    ) as client:
        return _get(client, f"/drucksache/{document_id}")


def fetch_beschlussempfehlungen(wahlperiode: int = 21) -> list[dict]:
    """Fetch all Beschlussempfehlungen for a Wahlperiode.

    List responses truncate ``vorgangsbezug`` (``vorgangsbezug_anzahl`` gives
    the true count); those documents are re-fetched individually so every
    Vorgang they cover is known.
    """
    documents = _fetch_drucksachen(BESCHLUSSEMPFEHLUNG_TYP, wahlperiode=wahlperiode)
    return [
        fetch_drucksache(doc["id"])
        if (doc.get("vorgangsbezug_anzahl") or 0) > len(doc.get("vorgangsbezug") or [])
        else doc
        for doc in documents
    ]


def fetch_beratungsstand(vorgang_id: str) -> str | None:
    """Fetch the ``beratungsstand`` of a Vorgang, or ``None`` if absent."""
    if not vorgang_id:
        return None
    with httpx.Client(
        base_url=config.DIP_BASE_URL,
        headers=config.dip_headers(),
        timeout=_TIMEOUT,
    ) as client:
        data = _get(client, f"/vorgang/{vorgang_id}")
    return data.get("beratungsstand")


def document_to_bill(doc: dict) -> dict:
    """Map a DIP Drucksache document to a bills-table dict.

    Pure function, defensive about missing keys. ``urheber`` is a list of dicts
    whose ``bezeichnung`` values are joined with ", "; ``vorgang_id`` comes from
    the first ``vorgangsbezug`` entry; ``pdf_url`` comes from
    ``fundstelle.pdf_url``.
    """
    urheber_list = doc.get("urheber") or []
    urheber = ", ".join(
        u.get("bezeichnung", "")
        for u in urheber_list
        if isinstance(u, dict) and u.get("bezeichnung")
    ) or None

    fundstelle = doc.get("fundstelle") or {}
    pdf_url = fundstelle.get("pdf_url")

    vorgangsbezug = doc.get("vorgangsbezug") or []
    bezug = vorgangsbezug[0] if vorgangsbezug and isinstance(vorgangsbezug[0], dict) else None
    vorgang_id = bezug.get("id") if bezug else None

    return {
        "id": doc.get("id"),
        "dokumentnummer": doc.get("dokumentnummer"),
        "wahlperiode": doc.get("wahlperiode"),
        "titel": doc.get("titel"),
        "urheber": urheber,
        "datum": doc.get("datum"),
        "aktualisiert": doc.get("aktualisiert"),
        "pdf_hash": doc.get("pdf_hash"),
        "pdf_url": pdf_url,
        "vorgang_id": vorgang_id,
    }


def document_to_related(doc: dict, typ: str) -> dict:
    """Map a DIP Drucksache to a ``bill_documents`` row (without ``bill_id``)."""
    fundstelle = doc.get("fundstelle") or {}
    return {
        "document_id": doc.get("id"),
        "typ": typ,
        "dokumentnummer": doc.get("dokumentnummer"),
        "titel": doc.get("titel"),
        "datum": doc.get("datum") or fundstelle.get("datum"),
        "aktualisiert": doc.get("aktualisiert"),
        "pdf_url": fundstelle.get("pdf_url"),
        "pdf_hash": doc.get("pdf_hash"),
    }


def index_by_vorgang(documents: list[dict], typ: str) -> dict[str, list[dict]]:
    """Map every Vorgang id to the related-document rows that reference it.

    A document covering several Vorgänge appears under each of them; documents
    without a PDF are left out. Each list is ordered by ``datum``, then
    ``dokumentnummer``.
    """
    index: dict[str, list[dict]] = {}
    for doc in documents:
        related = document_to_related(doc, typ)
        if not related["pdf_url"]:
            continue
        for bezug in doc.get("vorgangsbezug") or []:
            if isinstance(bezug, dict) and bezug.get("id"):
                index.setdefault(bezug["id"], []).append(related)
    for rows in index.values():
        rows.sort(key=lambda r: (r["datum"] or "", r["dokumentnummer"] or ""))
    return index
