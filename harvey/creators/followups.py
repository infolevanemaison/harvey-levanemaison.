"""What needs doing today, and what to do with a creator's reply.

`due_actions` reads the local store and lists every pending step with the
command that does it, so a person (or Claude, asked from the phone) can
work through the list. It never acts by itself.

`handle_reply` applies the rules that must not depend on a model: an
opt-out erases her data at once; a legal or complaint keyword sends the
conversation to a person with no suggested answer. Anything else gets a
suggested reply that waits for approval like every other message.
"""

from datetime import date, timedelta

from harvey.agents.handler import ESCALATION_PATTERNS, _flat, _opt_out_reason
from harvey.locales import fold

FOLLOW_UP_AFTER_DAYS = 7      # one reminder, never more
CLOSE_AFTER_DAYS = 21         # no answer to the first message and the reminder
REVIEW_STALE_DAYS = 2
DRAFT_UNSENT_DAYS = 3
SHIP_WITHIN_DAYS = 5
MEASURE_AFTER_DAYS = 14


def _day(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def due_actions(store, today: date | None = None) -> list[dict]:
    today = today or date.today()
    actions: list[dict] = []

    def add(priority: int, row_id: str, who: str, what: str, how: str):
        actions.append({"priority": priority, "id": row_id, "who": who, "what": what, "how": how})

    creators = {r["id"]: r for r in store.list_creators()}
    handle = lambda cid: "@" + creators[cid]["handle"] if cid in creators else cid  # noqa: E731
    proposals = store.list_proposals()
    by_creator: dict[str, list[dict]] = {}
    for p in proposals:
        by_creator.setdefault(p["creator_id"], []).append(p)

    for p in proposals:
        made = _day(p.get("updated_at") or p.get("created_at"))
        age = (today - made).days if made else 0
        if p["status"] == "pending_review" and age >= REVIEW_STALE_DAYS:
            add(2, p["id"], handle(p["creator_id"]), f"Propuesta esperando tu revisión desde hace {age} días",
                f"harvey creators show-proposal {p['id']}")
        if p["status"] == "drafted" and age >= DRAFT_UNSENT_DAYS:
            add(2, p["id"], handle(p["creator_id"]), "Borrador en Gmail sin marcar como enviado",
                f"si ya lo enviaste: harvey creators sent {p['id']}")

    for cid, items in by_creator.items():
        row = creators.get(cid)
        if row is None or row["status"] != "contacted":
            continue
        first = [p for p in items if p.get("kind", "first") == "first" and p["status"] == "sent"]
        followups = [p for p in items if p.get("kind") == "followup"]
        if not first:
            continue
        sent_on = _day(first[-1].get("sent_on"))
        if not sent_on:
            continue
        waited = (today - sent_on).days
        if not followups and waited >= FOLLOW_UP_AFTER_DAYS:
            add(3, cid, handle(cid), f"Sin respuesta en {waited} días: un único recordatorio, o cerrarla",
                f"harvey creators followup {cid}")
        elif waited >= CLOSE_AFTER_DAYS and all(f["status"] in ("sent", "rejected") for f in followups):
            add(4, cid, handle(cid), "Sin respuesta tras el recordatorio: cerrar sin volver a escribir",
                f"harvey creators reject {cid}")

    for k in store.collaborations():
        who = handle(k["creator_id"])
        created = _day(k.get("created_at"))
        if k["status"] == "agreed" and created and (today - created).days >= SHIP_WITHIN_DAYS:
            add(2, k["id"], who, "Colaboración acordada y la prenda aún no consta como enviada",
                f"harvey creators collab-set {k['id']} shipped_on=AAAA-MM-DD status=shipped")
        due = _day(k.get("content_due"))
        if k["status"] == "shipped" and due and today > due:
            add(3, k["id"], who, f"La publicación debía salir el {due.isoformat()}",
                "escríbele (borrador) o anota la URL: "
                f"harvey creators collab-set {k['id']} post_urls=URL status=published")
        if k["status"] == "published":
            if k.get("labelled_as_ad") == 0:
                add(1, k["id"], who, "Publicación SIN etiquetar como publicidad: pídele que la "
                                     "etiquete (obligatorio)",
                    f"harvey creators collab-set {k['id']} labelled_as_ad=1 cuando esté corregida")
            elif k.get("labelled_as_ad") is None:
                add(1, k["id"], who, "Comprueba que la publicación está etiquetada como publicidad",
                    f"harvey creators collab-set {k['id']} labelled_as_ad=1 (o 0)")
            updated = _day(k.get("updated_at"))
            if updated and (today - updated).days >= MEASURE_AFTER_DAYS:
                add(3, k["id"], who, "Han pasado 2 semanas: mide visitas, pedidos y rentabilidad",
                    "harvey creators queries --month AAAA-MM, y luego report")

    stale = [r for r in creators.values() if r["status"] == "candidate"
             and _day(r.get("updated_at")) and (today - _day(r["updated_at"])).days >= 180]
    if stale:
        add(5, "-", f"{len(stale)} candidatas", "Llevan más de 6 meses sin aprobarse: bórralas",
            "harvey creators purge")
    return sorted(actions, key=lambda a: a["priority"])


def classify_reply(text: str) -> tuple[str, str]:
    """('opt_out' | 'escalate' | 'answer', why). Rules, not a model."""
    reason = _opt_out_reason(text, text)
    if reason:
        return "opt_out", reason["why"]
    flat = fold(_flat(text))
    hits = [p for p in ESCALATION_PATTERNS if p in flat]
    if hits:
        return "escalate", f"menciona {', '.join(hits[:3])}: la atiende una persona"
    return "answer", ""


async def handle_reply(store, cid: str, text: str, brain, config,
                       message_id: str = "", thread_subject: str = "") -> dict:
    """Record her reply and do what the rules say. Returns what happened."""
    row = store.get(cid)
    if row is None:
        raise KeyError(cid)
    if row["status"] == "opted_out":
        return {"outcome": "ignored", "why": "ya se dio de baja; no se le escribe"}
    outcome, why = classify_reply(text)
    if outcome == "opt_out":
        store.forget(cid)
        return {"outcome": "opt_out", "why": why}
    if outcome == "escalate":
        store.set_status(cid, "replied", notes="revisión humana: " + why)
        return {"outcome": "escalate", "why": why}
    if row["status"] in ("contacted", "drafted", "approved"):
        store.set_status(cid, "replied")
    from harvey.creators.proposals import write_reply
    language, subject, body, issues = await write_reply(brain, row["creator"], config, text,
                                                        thread_subject)
    pid = store.add_proposal(cid, language, subject, body, issues, kind="reply",
                             reply_to=message_id)
    return {"outcome": "answer", "proposal_id": pid, "subject": subject, "body": body,
            "issues": issues}
