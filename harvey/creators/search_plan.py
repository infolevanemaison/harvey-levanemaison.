"""Which web searches to run today for new creators, and what past ones gave.

The daily routine may run at most six web searches and add at most three new
candidates. Repeating the same phrasing day after day returns the same press
lists and the same names, so nothing new comes in. This module keeps a list
of query templates and a log of what each run returned, and picks today's
searches from them:

- a query that names a source the owner has excluded (by default Collabstr,
  whose terms forbid automated access without written permission) is never
  picked;
- a query used in the last ``cooldown_days`` days waits, also when it was
  written with the same words in another order, case or accents;
- a query whose last ``retire_after`` uses brought no new candidate is set
  aside for the owner to replace (never deleted);
- the rest go first if never used, then by type (media kits and blogs, where
  a creator publishes her own numbers and channel, before press lists),
  market (ES before FR, with a share kept for FR) and oldest use.

``check_log`` reads the log back and reports any run that broke a limit,
used an excluded source or gave a reason outside the shared vocabulary.

It only reads two CSV files and prints a plan. It runs no search, visits no
page and changes no limit: ``n`` can never exceed the routine's six.
"""

import csv
import os
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

MAX_SEARCHES = 6
MAX_NEW = 3
# Order of preference. Media kits and blogs are where a creator publishes
# her own numbers and a channel for brands; press lists mostly name large
# accounts with no channel.
TYPES = ("mediakit", "blog", "plataforma", "prensa")
MARKETS = ("ES", "FR")
# The owner checked Collabstr's terms: no automated access or collection
# without written permission. Add others with ``blocked=``.
BLOCKED_SOURCES = ("collabstr",)
# Why a result did not become a new candidate. One or more per search,
# separated by ";". Size is not here on purpose: follower count is scored,
# never a reason to leave a creator out, so the log flags it as unknown.
REASONS = {
    "duplicada": "ya estaba en la cartera",
    "sin_canal": "sin canal de colaboraciones publicado",
    "fuera_mercado": "ni España ni Francia",
    "fuera_nicho": "no es moda femenina",
    "fuera_edad": "audiencia fuera de 35-65",
    "idioma": "ni español ni francés",
    "sin_datos": "sin datos públicos que comprobar",
    "solo_redes": "solo se podía comprobar en redes sociales",
    "fuente_no_permitida": "la fuente no permite este método de consulta",
    "limite": "ya se habían añadido 3 candidatas",
    "sin_resultados": "la búsqueda no devolvió nada útil",
}


@dataclass
class Query:
    text: str
    market: str = "ES"
    kind: str = "prensa"


@dataclass
class Use:
    day: date
    text: str
    run: str = ""
    market: str = ""
    results: int = 0
    new: int = 0
    duplicates: int = 0
    duplicate_ids: list[str] = field(default_factory=list)
    discarded: int = 0
    reasons: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass
class Plan:
    today: list[Query]
    waiting: list[Query]
    retired: list[Query]
    blocked: list[Query]


def _int(value) -> int:
    try:
        return int(str(value).strip() or 0)
    except ValueError:
        return 0


def _list(value, sep: str = ";") -> list[str]:
    return [v.strip() for v in str(value or "").split(sep) if v.strip()]


def query_key(text: str) -> str:
    """Same words, any order, case, quotes or accents → same key."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    for ch in "\"'«»“”":
        plain = plain.replace(ch, " ")
    return " ".join(sorted(plain.split()))


def is_blocked(text: str, blocked=BLOCKED_SOURCES) -> bool:
    low = text.lower()
    return any(b and b.lower() in low for b in blocked)


def load_templates(path: str) -> list[Query]:
    """``consulta,mercado,tipo``. Blank or repeated queries are skipped."""
    seen, out = set(), []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            text = " ".join((row.get("consulta") or "").split())
            if not text or query_key(text) in seen:
                continue
            seen.add(query_key(text))
            market = (row.get("mercado") or "ES").strip().upper()
            kind = (row.get("tipo") or "prensa").strip().lower()
            out.append(Query(text, market if market in MARKETS else "ES",
                             kind if kind in TYPES else "prensa"))
    return out


def load_log(path: str) -> list[Use]:
    """``fecha,ejecucion,consulta,mercado,resultados,nuevas,duplicadas,
    ids_duplicadas,descartadas,motivos,fuentes``. Lists use ";". Rows from
    the first format (``conocidas``, ``motivo``) are read too."""
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                day = date.fromisoformat((row.get("fecha") or "").strip())
            except ValueError:
                continue
            out.append(Use(
                day, " ".join((row.get("consulta") or "").split()),
                run=(row.get("ejecucion") or "").strip() or day.isoformat(),
                market=(row.get("mercado") or "").strip().upper(),
                results=_int(row.get("resultados")), new=_int(row.get("nuevas")),
                duplicates=_int(row.get("duplicadas") or row.get("conocidas")),
                duplicate_ids=_list(row.get("ids_duplicadas")),
                discarded=_int(row.get("descartadas")),
                reasons=_list(row.get("motivos") or row.get("motivo")),
                sources=_list(row.get("fuentes"))))
    return out


def plan(templates: list[Query], log: list[Use], today: date, n: int = MAX_SEARCHES,
         cooldown_days: int = 14, retire_after: int = 2, fr_share: int = 2,
         blocked=BLOCKED_SOURCES) -> Plan:
    n = max(0, min(n, MAX_SEARCHES))
    uses: dict[str, list[Use]] = {}
    for u in sorted(log, key=lambda u: u.day):
        uses.setdefault(query_key(u.text), []).append(u)

    ready, waiting, retired, excluded = [], [], [], []
    for q in templates:
        if is_blocked(q.text, blocked):
            excluded.append(q)
            continue
        past = uses.get(query_key(q.text), [])
        last = past[-retire_after:] if retire_after > 0 else []
        if retire_after > 0 and len(last) == retire_after and all(u.new == 0 for u in last):
            retired.append(q)
        elif past and past[-1].day > today - timedelta(days=cooldown_days):
            waiting.append(q)
        else:
            ready.append((q, past[-1].day if past else None))

    ready.sort(key=lambda item: (item[1] is not None, TYPES.index(item[0].kind),
                                 MARKETS.index(item[0].market), item[1] or date.min))
    # Spain first, but keep up to ``fr_share`` places for France when it has
    # queries ready, so one market never takes the whole day.
    fr = [q for q, _ in ready if q.market == "FR"][:min(fr_share, n)]
    rest = [q for q, _ in ready if q not in fr][:n - len(fr)]
    chosen = [q for q, _ in ready if q in rest or q in fr]
    return Plan(chosen, waiting, retired, excluded)


def check_log(log: list[Use], blocked=BLOCKED_SOURCES) -> list[str]:
    """What in the log breaks a rule. Empty when everything is in order."""
    problems = []
    runs: dict[str, list[Use]] = {}
    for u in log:
        runs.setdefault(u.run, []).append(u)
    for run, rows in sorted(runs.items()):
        if len(rows) > MAX_SEARCHES:
            problems.append(f"{run}: {len(rows)} búsquedas (máximo {MAX_SEARCHES})")
        new = sum(u.new for u in rows)
        if new > MAX_NEW:
            problems.append(f"{run}: {new} candidatas nuevas (máximo {MAX_NEW})")
    for u in log:
        for s in [u.text, *u.sources]:
            if is_blocked(s, blocked):
                problems.append(f"{u.run}: fuente excluida en «{s}»")
        unknown = [r for r in u.reasons if r not in REASONS]
        if unknown:
            problems.append(f"{u.run}: motivo desconocido {', '.join(unknown)} en «{u.text}»")
        if u.duplicates and len(u.duplicate_ids) != u.duplicates:
            problems.append(f"{u.run}: {u.duplicates} duplicadas pero {len(u.duplicate_ids)} ids "
                            f"en «{u.text}»")
        if u.new == 0 and not u.reasons:
            problems.append(f"{u.run}: sin candidatas nuevas y sin motivo en «{u.text}»")
    return problems


def yield_by_type(templates: list[Query], log: list[Use]) -> dict[str, dict[str, int]]:
    """Counts straight from the log: searches run and candidates they brought."""
    kind_of = {query_key(q.text): q.kind for q in templates}
    out: dict[str, dict[str, int]] = {}
    for u in log:
        row = out.setdefault(kind_of.get(query_key(u.text), "sin plantilla"),
                             {"busquedas": 0, "nuevas": 0, "duplicadas": 0, "descartadas": 0})
        row["busquedas"] += 1
        row["nuevas"] += u.new
        row["duplicadas"] += u.duplicates
        row["descartadas"] += u.discarded
    return out


def reasons_count(log: list[Use]) -> dict[str, int]:
    out: dict[str, int] = {}
    for u in log:
        for r in u.reasons:
            out[r] = out.get(r, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
