"""From an approved proposal to a Gmail draft. Never to a sent email.

Two ways to make the draft, both behind the same checks:
- `harvey creators draft <id>` on a machine where `harvey gmail auth` ran;
- from a Claude Code session on the phone, through the Gmail connector:
  `harvey creators draft <id> --export` prints the checked draft as JSON
  and Claude creates it with the connector's create_draft, never send.
"""

from harvey.config import live_do_not_contact
from harvey.gate import do_not_contact_match
from harvey.creators.proposals import check_proposal


# Where a creator must be for each kind of message to be drafted.
ALLOWED_STATUS = {
    "first": ("approved", "drafted"),
    "followup": ("contacted",),
    "reply": ("replied", "negotiating", "collaborating", "contacted"),
}


class DraftRefused(RuntimeError):
    """Why this proposal may not become a draft."""


def ready_draft(store, proposal_id: str, config) -> dict:
    """The draft to create, after every check, or DraftRefused."""
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise DraftRefused(f"no proposal {proposal_id}")
    if proposal["status"] == "drafted":
        raise DraftRefused(f"proposal {proposal_id} already has a Gmail draft "
                           f"({proposal['draft_ref']}): send or delete that one")
    if proposal["status"] != "approved":
        raise DraftRefused(f"proposal {proposal_id} is {proposal['status']}: a person must "
                           "approve it first (harvey creators approve-proposal)")
    row = store.get(proposal["creator_id"])
    if row is None:
        raise DraftRefused("its creator no longer exists")
    if row["status"] in ("opted_out", "rejected"):
        raise DraftRefused(f"the creator is {row['status']}")
    kind = proposal.get("kind") or "first"
    allowed = ALLOWED_STATUS[kind]
    if row["status"] not in allowed:
        if kind == "first":
            raise DraftRefused("the creator hasn't been approved for contact "
                               "(harvey creators approve)")
        raise DraftRefused(f"a {kind} needs the creator to be {' or '.join(allowed)}, "
                           f"she is {row['status']}")
    creator = row["creator"]
    if not creator.pro_contact_email or not creator.pro_contact_source:
        raise DraftRefused("she doesn't publish a professional contact: write only "
                           "through the channel she offers")
    blocked = do_not_contact_match(creator.pro_contact_email, live_do_not_contact(config))
    if blocked:
        raise DraftRefused(f"{creator.pro_contact_email} is on the do-not-contact list")
    # The text may have been approved under older conditions: check again now.
    # First messages and reminders end with the footer, which isn't checked.
    body = proposal["body"].split("\n\n")
    own_words = ("\n\n".join(body[:-1]) if kind != "reply" and len(body) > 1
                 else proposal["body"])
    issues = check_proposal(proposal["subject"], own_words, proposal["language"],
                            config.creators.offer)
    if kind == "reply":
        issues = [i for i in issues if not i.startswith("está escrito en")]
    if issues:
        raise DraftRefused("the text no longer passes the checks: " + "; ".join(issues))
    return {"to": creator.pro_contact_email, "subject": proposal["subject"],
            "body": proposal["body"], "proposal_id": proposal_id,
            "creator_id": proposal["creator_id"], "kind": kind,
            # For the Gmail connector: answer inside her thread.
            "reply_to_message_id": proposal.get("reply_to") or ""}


async def create_gmail_draft(store, proposal_id: str, config, provider) -> str:
    """Create the draft with Harvey's own Gmail connection. Returns its ref."""
    draft = ready_draft(store, proposal_id, config)
    result = await provider.create_draft(draft["to"], draft["subject"], draft["body"])
    if not result.ok:
        raise DraftRefused(f"Gmail didn't save the draft: {result.error}")
    mark_drafted(store, draft, result.message_id)
    return result.message_id


def mark_drafted(store, draft: dict, ref: str) -> None:
    store.set_proposal_status(draft["proposal_id"], "drafted", draft_ref=ref or "connector")
    if draft.get("kind", "first") == "first":
        store.set_status(draft["creator_id"], "drafted")
