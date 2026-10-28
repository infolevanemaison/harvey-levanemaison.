"""Remember alerts between runs, and write what the owner reads.

``update_state`` compares today's alerts with the saved state: an alert is
*new* the first time it appears, *open* while it lasts and *resolved* when a
run no longer sees it. Only new alerts, and open ones whose severity rose,
are worth a notification; the rest go in the digest. ``decisions`` gathers
every open alert that needs the owner into one ranked list, so she gets one
report instead of a stream of questions.
"""

import json
import os
from dataclasses import asdict
from datetime import datetime

from harvey.watch.checks import SEVERITIES, URGENT, Alert


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {"open": {}, "resolved": []}
    with open(path, encoding="utf-8") as f:
        state = json.load(f)
    state.setdefault("open", {})
    state.setdefault("resolved", [])
    return state


def save_state(state: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def update_state(state: dict, alerts: list[Alert], now: datetime, unchecked=()) -> dict:
    """Return {"new", "escalated", "open", "resolved"} and update ``state``.

    An area that could not be checked this run keeps its open alerts as they
    are: not seeing a problem because nobody looked is not a resolution.
    """
    stamp = now.isoformat(timespec="minutes")
    seen = {a.fingerprint: a for a in alerts}
    new, escalated = [], []
    for fp, a in seen.items():
        prev = state["open"].get(fp)
        if prev is None:
            new.append(a)
            state["open"][fp] = {**asdict(a), "first_seen": stamp, "last_seen": stamp}
            continue
        if SEVERITIES.index(a.severity) < SEVERITIES.index(prev["severity"]):
            escalated.append(a)
        state["open"][fp] = {**asdict(a), "first_seen": prev["first_seen"], "last_seen": stamp}
    resolved = []
    for fp in list(state["open"]):
        if fp in seen or _area(state["open"][fp]["code"]) in unchecked:
            continue
        item = state["open"].pop(fp)
        item["resolved_at"] = stamp
        resolved.append(item)
    state["resolved"] = (state["resolved"] + resolved)[-200:]
    state["last_run"] = stamp
    return {"new": new, "escalated": escalated, "open": list(state["open"].values()),
            "resolved": resolved}


AREAS = {
    "pedido_sin_enviar": "pedidos y entregas", "entrega_fallida": "pedidos y entregas",
    "sin_seguimiento": "pedidos y entregas", "entrega_retrasada": "pedidos y entregas",
    "pedidos_manuales_cancelados": "pedidos y entregas", "tema_de_pruebas_publicado": "tema publicado",
    "catalogo_critico": "catálogo", "venta_sin_stock": "catálogo", "campana_activa": "Meta Ads",
    "gasto_sin_ventas": "Meta Ads", "gasto_sobre_limite": "Meta Ads", "gasto_antes_de_pausa": "Meta Ads",
}


def _area(code: str) -> str:
    return AREAS.get(code, "")


def should_notify(change: dict) -> list[Alert]:
    """What deserves a push or an issue now: new or escalated, high or urgent."""
    return [a for a in change["new"] + change["escalated"] if SEVERITIES.index(a.severity) <= 1]


def digest(change: dict, now: datetime, unchecked=()) -> str:
    lines = [f"# Vigilancia · {now.strftime('%Y-%m-%d %H:%M')} UTC", ""]
    urgent = [a for a in change["open"] if a["severity"] == URGENT]
    lines.append(f"**Abiertas:** {len(change['open'])} ({len(urgent)} urgentes) · "
                 f"**nuevas:** {len(change['new'])} · **resueltas:** {len(change['resolved'])}")
    if unchecked:
        lines.append(f"**Sin comprobar (sin datos):** {', '.join(unchecked)}")
    lines.append("")
    for title, items in (("Nuevas", [asdict(a) for a in change["new"]]),
                         ("Abiertas", change["open"]), ("Resueltas", change["resolved"])):
        if not items:
            continue
        lines += [f"## {title}", ""]
        for a in sorted(items, key=lambda x: SEVERITIES.index(x["severity"])):
            since = f" (desde {a['first_seen']})" if a.get("first_seen") and title == "Abiertas" else ""
            lines.append(f"- **{a['severity']}** · {a['message']}{since} → {a['action']}")
        lines.append("")
    return "\n".join(lines)


def decisions(state: dict) -> str:
    """One ranked list of everything waiting on the owner."""
    items = sorted((a for a in state["open"].values() if a.get("needs_owner")),
                   key=lambda a: (SEVERITIES.index(a["severity"]), a["first_seen"]))
    lines = ["# Decisiones pendientes (vigilancia)", "",
             "Ordenadas por urgencia. Harvey no actúa sobre ninguna sin tu aprobación.", ""]
    if not items:
        lines.append("Nada pendiente.")
    for i, a in enumerate(items, 1):
        lines.append(f"{i}. **{a['severity']}** · {a['message']} → {a['action']} "
                     f"(abierta desde {a['first_seen']})")
    return "\n".join(lines) + "\n"
