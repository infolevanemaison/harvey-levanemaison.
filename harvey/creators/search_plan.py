"""Which web searches to run today for new creators, and what past ones gave.

The daily routine may run at most six web searches. Repeating the same
phrasing day after day returns the same press lists and the same names, so
nothing new comes in. This module keeps a list of query templates and a log
of what each run returned, and picks today's searches from them:

- a query used in the last ``cooldown_days`` days waits;
- a query whose last ``retire_after`` uses brought no new candidate is set
  aside for the owner to replace (never deleted);
- the rest go first if never used, then by type (pages where creators
  publish a collaborations channel before press lists), market (ES before
  FR) and oldest use.

It only reads two CSV files and prints a plan. It runs no search, visits no
page and changes no limit: ``n`` can never exceed the routine's six.
"""

import csv
import os
from dataclasses import dataclass
from datetime import date, timedelta

MAX_SEARCHES = 6
# Order of preference. Platform listings and media kits are where a creator
# publishes a channel for brands or audited numbers; press lists mostly name
# large accounts with no channel.
TYPES = ("plataforma", "mediakit", "blog", "prensa")
MARKETS = ("ES", "FR")


@dataclass
class Query:
    text: str
    market: str = "ES"
    kind: str = "prensa"


@dataclass
class Use:
    day: date
    text: str
    results: int = 0
    new: int = 0
    known: int = 0
    discarded: int = 0
    reason: str = ""


@dataclass
class Plan:
    today: list[Query]
    waiting: list[Query]
    retired: list[Query]


def _int(value) -> int:
    try:
        return int(str(value).strip() or 0)
    except ValueError:
        return 0


def load_templates(path: str) -> list[Query]:
    """``consulta,mercado,tipo``. Blank or repeated queries are skipped."""
    seen, out = set(), []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            text = " ".join((row.get("consulta") or "").split())
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            market = (row.get("mercado") or "ES").strip().upper()
            kind = (row.get("tipo") or "prensa").strip().lower()
            out.append(Query(text, market if market in MARKETS else "ES",
                             kind if kind in TYPES else "prensa"))
    return out


def load_log(path: str) -> list[Use]:
    """``fecha,consulta,resultados,nuevas,conocidas,descartadas,motivo``."""
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                day = date.fromisoformat((row.get("fecha") or "").strip())
            except ValueError:
                continue
            out.append(Use(day, " ".join((row.get("consulta") or "").split()),
                           _int(row.get("resultados")), _int(row.get("nuevas")),
                           _int(row.get("conocidas")), _int(row.get("descartadas")),
                           (row.get("motivo") or "").strip()))
    return out


def plan(templates: list[Query], log: list[Use], today: date, n: int = MAX_SEARCHES,
         cooldown_days: int = 14, retire_after: int = 2) -> Plan:
    n = max(0, min(n, MAX_SEARCHES))
    uses: dict[str, list[Use]] = {}
    for u in sorted(log, key=lambda u: u.day):
        uses.setdefault(u.text.lower(), []).append(u)

    ready, waiting, retired = [], [], []
    for q in templates:
        past = uses.get(q.text.lower(), [])
        last = past[-retire_after:] if retire_after > 0 else []
        if len(last) == retire_after and retire_after > 0 and all(u.new == 0 for u in last):
            retired.append(q)
        elif past and past[-1].day > today - timedelta(days=cooldown_days):
            waiting.append(q)
        else:
            ready.append((q, past[-1].day if past else None))

    ready.sort(key=lambda item: (item[1] is not None, TYPES.index(item[0].kind),
                                 MARKETS.index(item[0].market), item[1] or date.min))
    return Plan([q for q, _ in ready[:n]], waiting, retired)


def yield_by_type(templates: list[Query], log: list[Use]) -> dict[str, dict[str, int]]:
    """Counts straight from the log: searches run and candidates they brought."""
    kind_of = {q.text.lower(): q.kind for q in templates}
    out: dict[str, dict[str, int]] = {}
    for u in log:
        row = out.setdefault(kind_of.get(u.text.lower(), "sin plantilla"),
                             {"busquedas": 0, "nuevas": 0, "conocidas": 0, "descartadas": 0})
        row["busquedas"] += 1
        row["nuevas"] += u.new
        row["conocidas"] += u.known
        row["descartadas"] += u.discarded
    return out
