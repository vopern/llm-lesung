"""Pure mapping tests for document_to_bill (no network)."""

from backend.dip import client
from backend.dip.client import document_to_bill, document_to_related, index_by_vorgang


SAMPLE_DOC = {
    "id": "294216",
    "dokumentnummer": "21/6916",
    "wahlperiode": 21,
    "titel": "Entwurf eines Gesetzes zur Änderung des Musterrechts",
    "datum": "2026-06-10",
    "aktualisiert": "2026-06-12T14:03:21+02:00",
    "pdf_hash": "deadbeef",
    "urheber": [
        {"bezeichnung": "Bundesregierung", "einbringer": True},
        {"bezeichnung": "Fraktion X", "einbringer": False},
    ],
    "fundstelle": {
        "pdf_url": "https://dserver.bundestag.de/btd/21/069/2106916.pdf",
        "seite": "1",
    },
    "vorgangsbezug": [
        {"id": "312044", "titel": "Musterrecht", "vorgangstyp": "Gesetzgebung"},
        {"id": "999999", "titel": "Anderer", "vorgangstyp": "Gesetzgebung"},
    ],
}


def test_document_to_bill_full():
    bill = document_to_bill(SAMPLE_DOC)
    assert bill["id"] == "294216"
    assert bill["dokumentnummer"] == "21/6916"
    assert bill["wahlperiode"] == 21
    assert bill["titel"] == "Entwurf eines Gesetzes zur Änderung des Musterrechts"
    assert bill["urheber"] == "Bundesregierung, Fraktion X"
    assert bill["datum"] == "2026-06-10"
    assert bill["aktualisiert"] == "2026-06-12T14:03:21+02:00"
    assert bill["pdf_hash"] == "deadbeef"
    assert bill["pdf_url"] == "https://dserver.bundestag.de/btd/21/069/2106916.pdf"
    assert bill["vorgang_id"] == "312044"  # first vorgangsbezug only


def test_document_to_bill_missing_fields():
    bill = document_to_bill({"id": "1", "dokumentnummer": "21/1", "wahlperiode": 21, "titel": "T"})
    assert bill["id"] == "1"
    assert bill["urheber"] is None
    assert bill["datum"] is None
    assert bill["aktualisiert"] is None
    assert bill["pdf_hash"] is None
    assert bill["pdf_url"] is None
    assert bill["vorgang_id"] is None


def test_document_to_bill_empty_lists_and_dicts():
    bill = document_to_bill({
        "id": "2",
        "urheber": [],
        "fundstelle": {},
        "vorgangsbezug": [],
    })
    assert bill["urheber"] is None
    assert bill["pdf_url"] is None
    assert bill["vorgang_id"] is None


def test_document_to_bill_urheber_missing_bezeichnung():
    bill = document_to_bill({
        "id": "3",
        "urheber": [{"einbringer": True}, {"bezeichnung": "Bundesrat"}],
    })
    assert bill["urheber"] == "Bundesrat"


def test_document_to_bill_empty():
    bill = document_to_bill({})
    assert bill["id"] is None
    assert bill["pdf_url"] is None
    assert bill["vorgang_id"] is None
    assert bill["urheber"] is None


BE_DOC = {
    "id": "290645",
    "dokumentnummer": "21/7949",
    "titel": "Beschlussempfehlung und Bericht zu dem Gesetzentwurf",
    "datum": "2026-09-09",
    "aktualisiert": "2026-09-10T10:59:54+02:00",
    "pdf_hash": "01cca247",
    "vorgangsbezug_anzahl": 2,
    "vorgangsbezug": [{"id": "335066"}, {"id": "335067"}],
    "fundstelle": {"pdf_url": "https://dserver.bundestag.de/btd/21/079/2107949.pdf"},
}


def test_document_to_related():
    assert document_to_related(BE_DOC, "beschlussempfehlung") == {
        "document_id": "290645",
        "typ": "beschlussempfehlung",
        "dokumentnummer": "21/7949",
        "titel": "Beschlussempfehlung und Bericht zu dem Gesetzentwurf",
        "datum": "2026-09-09",
        "aktualisiert": "2026-09-10T10:59:54+02:00",
        "pdf_url": "https://dserver.bundestag.de/btd/21/079/2107949.pdf",
        "pdf_hash": "01cca247",
    }


def test_document_to_related_datum_falls_back_to_fundstelle():
    doc = {"id": "1", "fundstelle": {"datum": "2026-01-05"}}
    assert document_to_related(doc, "beschlussempfehlung")["datum"] == "2026-01-05"


def test_index_by_vorgang_fans_out_and_skips_pdfless():
    pdfless = {"id": "2", "vorgangsbezug": [{"id": "335066"}], "fundstelle": {}}
    index = index_by_vorgang([BE_DOC, pdfless], "beschlussempfehlung")
    assert set(index) == {"335066", "335067"}
    assert [d["document_id"] for d in index["335066"]] == ["290645"]
    assert [d["document_id"] for d in index["335067"]] == ["290645"]


def test_index_by_vorgang_orders_by_datum_then_dokumentnummer():
    docs = [
        dict(BE_DOC, id="c", dokumentnummer="21/300", datum="2026-05-01"),
        dict(BE_DOC, id="b", dokumentnummer="21/200", datum="2026-04-01"),
        dict(BE_DOC, id="a", dokumentnummer="21/100", datum="2026-04-01"),
    ]
    index = index_by_vorgang(docs, "beschlussempfehlung")
    assert [d["document_id"] for d in index["335066"]] == ["a", "b", "c"]


def test_fetch_beschlussempfehlungen_detail_fetches_only_truncated(monkeypatch):
    complete = dict(BE_DOC, id="1", vorgangsbezug_anzahl=2)
    truncated = dict(BE_DOC, id="2", vorgangsbezug_anzahl=7)
    detailed = dict(truncated, vorgangsbezug=[{"id": str(i)} for i in range(7)])
    monkeypatch.setattr(
        client, "_fetch_drucksachen", lambda typ, wahlperiode=21: [complete, truncated]
    )
    detail_calls = []

    def _detail(document_id):
        detail_calls.append(document_id)
        return detailed

    monkeypatch.setattr(client, "fetch_drucksache", _detail)
    assert client.fetch_beschlussempfehlungen() == [complete, detailed]
    assert detail_calls == ["2"]
