"""Source: the federal law in force, from gesetze-im-internet.de (GII).

``index`` lists GII's laws (slug, abbreviation, title) from its Teillisten,
``client`` downloads and caches a law's ``xml.zip``, ``law`` reads one. A
paragraph's id is its GII path, ``<slug>/<unit>`` (``wehrpflg/__3``), so
``https://www.gesetze-im-internet.de/<id>.html`` is its page. GII holds only the
current version of a law. No model, no ``Reference``: callers pass plain values.
"""

BASE_URL = "https://www.gesetze-im-internet.de"


def url(paragraph_id: str) -> str:
    return f"{BASE_URL}/{paragraph_id}.html"
