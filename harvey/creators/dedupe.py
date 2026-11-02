"""The same person, found twice under different handles or sources.

Daily research must not spend time (or a stranger's patience) on someone
already in the list. Two rows are the same person when their names match,
their handles match once separators are ignored, or they point to the same
page and share part of the name. A shared listing page alone (a platform's
city ranking, a press article) is not enough: many people appear on it.
"""

import re
from urllib.parse import urlparse

from harvey.locales import fold


def _name(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", fold(text or ""))


def _first(text: str) -> str:
    """The first name, which two different people on one page rarely share
    together with that page (surnames like a shared word often do)."""
    words = [t for t in re.split(r"[^a-z0-9]+", fold(text or "")) if t]
    return words[0] if words and len(words[0]) >= 3 else ""


def _url(text: str) -> str:
    if not text or "//" not in text:
        return ""
    u = urlparse(text.strip().lower())
    return (u.netloc.removeprefix("www.") + u.path.rstrip("/"))


def _urls(c) -> set[str]:
    return {u for u in (_url(c.profile_url), _url(c.pro_contact_source)) if u}


def same_person(a, b) -> str:
    """Why creators a and b look like the same person, or ""."""
    na, nb = _name(a.display_name), _name(b.display_name)
    if na and len(na) >= 6 and na == nb:
        return "mismo nombre"
    ha, hb = _name(a.handle), _name(b.handle)
    if ha and ha == hb:
        return "mismo usuario"
    shared = _urls(a) & _urls(b)
    if shared and _first(a.display_name) and _first(a.display_name) == _first(b.display_name):
        return "misma página y nombre parecido"
    return ""


def duplicates(rows: list[dict]) -> list[tuple[dict, dict, str]]:
    out = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            why = same_person(a["creator"], b["creator"])
            if why:
                out.append((a, b, why))
    return out


def find(rows: list[dict], text: str) -> list[dict]:
    """Rows whose name, handle or pages contain text (accents and case ignored)."""
    q = _name(text)
    if not q:
        return []
    hits = []
    for r in rows:
        c = r["creator"]
        hay = _name(c.display_name) + " " + _name(c.handle) + " " + " ".join(_urls(c))
        if q in hay.replace(".", "").replace("/", ""):
            hits.append(r)
    return hits
