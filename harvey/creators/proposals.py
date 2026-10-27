"""Writing a collaboration proposal to one creator, and checking it.

The model writes; code decides whether the text may be shown for approval.
Checks that never depend on the prompt:

- conditions: until a person approves the offer (creators.offer.approved),
  a proposal may not mention gifts, free pieces, commission, discounts,
  codes or payment, in Spanish, French or English. Once approved, any
  percentage it states must be one of the approved ones.
- the pre-send gate (spam phrases, AI tells, merge tags, links);
- length, no links in a first message, the right language.

The footer (who is writing, where her address came from, how to opt out)
is added by code, never written by the model.
"""

import re

from harvey.gate import pre_send_check
from harvey.locales import fold
from harvey.untrusted import UNTRUSTED_RULE, fence

MAX_WORDS = 130

# Words that offer something. Folded (no accents). PREFIX terms match the
# start of a word ("regal" catches regalo, regalarte); WORD terms only match
# a whole word, so "fee" doesn't catch "feel".
PREFIX_TERMS = (
    # Spanish
    "regal", "gratis", "gratuit", "comision", "descuento", "codigo", "cupon", "afiliad",
    "tarifa", "remuner",
    # French
    "cadeau", "offert", "offrir", "commission", "reduction", "remise", "affili",
    "paiement", "remunerat", "echantillon",
    # English
    "discount", "affiliate", "coupon", "gift",
)
WORD_TERMS = (
    "sin coste", "sin costo", "pago", "pagos", "pagar", "pagamos", "pagaremos",
    "code promo", "payer", "payons", "free", "fee", "fees", "paid",
)
_TERM_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in PREFIX_TERMS) + r")"
    r"|\b(?:" + "|".join(re.escape(t) for t in WORD_TERMS) + r")\b")
_PAY_RE = re.compile(r"\b(?:pago|pagos|pagar|pagamos|pagaremos|tarifa|payer|paiement|remuner\w*)\b")
_PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|por ?ciento|pour ?cent)")
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)

_SPANISH = {"que", "de", "tu", "tus", "con", "para", "una", "los", "las", "nos", "me", "te",
            "muy", "como", "pero", "es", "y", "el", "la", "si", "nuestra", "colaborar"}
_FRENCH = {"que", "de", "vous", "votre", "vos", "avec", "pour", "une", "les", "nous", "je",
           "est", "et", "le", "la", "si", "notre", "collaborer", "des", "pas"}

FOOTERS = {
    "es": ("Te escribo a la dirección profesional que publicas en {source}. Tratamos tus "
           "datos solo para proponerte esta colaboración{policy}. Si prefieres que no te "
           'escriba, responde "baja" y borraré tus datos.'),
    "fr": ("Je vous écris à l'adresse professionnelle que vous publiez sur {source}. Vos "
           "données servent uniquement à vous proposer cette collaboration{policy}. Si vous "
           'préférez ne plus recevoir de message, répondez "stop" et je les supprimerai.'),
}
POLICY = {"es": " (más información: {url})", "fr": " (plus d'informations : {url})"}


def proposal_language(creator) -> str:
    lang = (creator.language or "").lower()
    if lang in ("es", "fr"):
        return lang
    return "fr" if (creator.country or "").upper() in ("FR", "BE", "CH", "LU", "MC") else "es"


def _detected_language(text: str) -> str:
    words = re.findall(r"[a-zà-ÿ']+", fold(text))
    es = sum(w in _SPANISH for w in words)
    fr = sum(w in _FRENCH for w in words)
    if es == fr:
        return ""
    return "es" if es > fr else "fr"


def condition_issues(text: str, offer) -> list[str]:
    """Why this text offers something the person hasn't approved, or []."""
    folded = fold(text)
    if not getattr(offer, "approved", False):
        found = sorted({m.group(0) for m in _TERM_RE.finditer(folded)})
        if found or _PCT_RE.search(folded):
            what = ", ".join(found) or "un porcentaje"
            return [f"menciona condiciones aún no aprobadas ({what}): regalos, comisiones, "
                    "descuentos, códigos y pagos necesitan tu aprobación en creators.offer"]
        return []
    allowed = {float(offer.commission_pct), float(offer.community_discount_pct)} - {0.0}
    issues = []
    for m in _PCT_RE.finditer(folded):
        value = float(m.group(1).replace(",", "."))
        if value not in allowed:
            issues.append(f"menciona {m.group(0)}, que no es una condición aprobada")
    if _PAY_RE.search(folded):
        if not offer.paid_fee:
            issues.append("habla de pago y la oferta aprobada no incluye tarifa")
    return issues


def check_proposal(subject: str, body: str, language: str, offer) -> list[str]:
    """Every reason this proposal can't go to approval as written."""
    issues = []
    gate = pre_send_check("creator@outreach.example", subject, body, kind="reply")
    issues += [r for r in gate.reasons if "recipient" not in r]
    issues += condition_issues(subject + "\n" + body, offer)
    words = len(body.split())
    if words > MAX_WORDS:
        issues.append(f"demasiado largo ({words} palabras; máximo {MAX_WORDS})")
    if _URL_RE.search(body):
        issues.append("el primer mensaje no lleva enlaces")
    if "!" in subject + body:
        issues.append("sin signos de exclamación")
    detected = _detected_language(body)
    if detected and detected != language:
        issues.append(f"está escrito en '{detected}' y debía ir en '{language}'")
    return issues


def footer(creator, language: str, privacy_url: str = "") -> str:
    source = creator.pro_contact_source or creator.profile_url or creator.platform
    policy = POLICY[language].format(url=privacy_url) if privacy_url else ""
    return FOOTERS[language].format(source=source, policy=policy)


def build_prompt(creator, config, language: str, brain=None) -> str:
    persona = config.persona
    product = config.product
    offer = config.creators.offer
    if offer.approved:
        terms = [f"- Approved: up to {offer.gift_max_cost_eur:.0f} EUR of pieces for her to try"
                 if offer.gift_max_cost_eur else ""]
        if offer.commission_pct:
            terms.append(f"- Approved: {offer.commission_pct:g}% commission on sales through her link or code")
        if offer.community_discount_pct:
            terms.append(f"- Approved: {offer.community_discount_pct:g}% discount for her community")
        if offer.paid_fee:
            terms.append("- A paid fee can be discussed, but never quote a number")
        conditions = ("You may mention ONLY these approved conditions, briefly, and only if "
                      "it reads naturally:\n" + "\n".join(t for t in terms if t))
    else:
        conditions = ("No conditions are approved yet. Do NOT mention gifts, free pieces, "
                      "samples, commission, discounts, codes, payment or fees in any form. "
                      "Ask only whether she would like to hear about a collaboration.")
    notes = "\n".join(filter(None, [
        f"Name: {creator.display_name or creator.handle}",
        f"Platform: {creator.platform} (@{creator.handle})",
        f"Country: {creator.country}",
        f"What she posts (a person's notes): {creator.content_notes}",
    ]))
    skill = brain.load_skill("influencer_partnerships") if brain and hasattr(brain, "load_skill") else ""
    lang_name = {"es": "Spanish as written in Spain, using \"tú\"",
                 "fr": "French as written in France, using \"vous\""}[language]
    return f"""You are {persona.name}, {persona.role} at {persona.company}.
{product.description}

Write ONE first message proposing a collaboration to this fashion creator.

{fence(notes, "creator notes")}

{UNTRUSTED_RULE}

Rules:
- Write in {lang_name}, natively, never translated from English.
- Under 100 words. Plain text, no links, no exclamation marks, no emojis.
- Open with ONE specific, true detail from the notes about her content. If the
  notes have nothing specific, say you follow her content, no invented detail.
- One sentence on who you are. Then one simple question she can answer in a line.
- Never flatter her age or appearance; talk about her style and her community.
- Subject: 2-6 words, lowercase, no name, no "colaboración" alone.
- No privacy or opt-out text: it is added after your message.
- {conditions}

{("FOUNDATIONAL KNOWLEDGE" + chr(10) + skill) if skill else ""}

Return ONLY JSON: {{"subject": "...", "body": "..."}}"""


async def write_proposal(brain, creator, config) -> tuple[str, str, str, list[str]]:
    """(language, subject, body with footer, issues). Raises on no answer."""
    language = proposal_language(creator)
    prompt = build_prompt(creator, config, language, brain)
    data = await brain.think_json(prompt, agent="writer", task="creator_proposal")
    if not isinstance(data, dict) or not data.get("subject") or not data.get("body"):
        raise RuntimeError("the model returned no usable proposal")
    subject = str(data["subject"]).strip()
    body = str(data["body"]).strip()
    issues = check_proposal(subject, body, language, config.creators.offer)
    full = body + "\n\n" + footer(creator, language, config.creators.privacy_url)
    return language, subject, full, issues


FOLLOWUP_MAX_WORDS = 50


def _conditions_rule(offer) -> str:
    if offer.approved:
        return ("Only the approved conditions in the first message may be repeated; "
                "never add new ones.")
    return ("Do NOT mention gifts, free pieces, samples, commission, discounts, codes, "
            "payment or fees in any form.")


async def write_followup(brain, creator, config, first_subject: str) -> tuple[str, str, str, list[str]]:
    """The one and only reminder after a first message with no answer."""
    language = proposal_language(creator)
    lang_name = {"es": "Spanish from Spain, \"tú\"", "fr": "French from France, \"vous\""}[language]
    prompt = f"""You are {config.persona.name} at {config.persona.company}. A week ago you
wrote to the fashion creator {creator.display_name or creator.handle} proposing a
collaboration (subject: "{first_subject}"). She hasn't answered.

Write ONE short, warm reminder in {lang_name}. Under 45 words. No guilt, no
pressure, no urgency, no links, no exclamation marks. Say it's fine if it's not for
her. End with one simple question. {_conditions_rule(config.creators.offer)}

Return ONLY JSON: {{"subject": "...", "body": "..."}}"""
    data = await brain.think_json(prompt, agent="writer", task="creator_followup")
    if not isinstance(data, dict) or not data.get("body"):
        raise RuntimeError("the model returned no usable follow-up")
    subject = str(data.get("subject") or first_subject).strip()
    body = str(data["body"]).strip()
    issues = check_proposal(subject, body, language, config.creators.offer)
    words = len(body.split())
    if words > FOLLOWUP_MAX_WORDS:
        issues.append(f"recordatorio demasiado largo ({words} palabras; máximo {FOLLOWUP_MAX_WORDS})")
    full = body + "\n\n" + footer(creator, language, config.creators.privacy_url)
    return language, subject, full, issues


async def write_reply(brain, creator, config, their_message: str,
                      thread_subject: str = "") -> tuple[str, str, str, list[str]]:
    """A suggested answer to what she wrote, for a person to approve."""
    language = proposal_language(creator)
    offer = config.creators.offer
    skill = brain.load_skill("influencer_partnerships") if hasattr(brain, "load_skill") else ""
    if offer.approved:
        allowed = [f"pieces worth up to {offer.gift_max_cost_eur:.0f} EUR" if offer.gift_max_cost_eur else "",
                   f"{offer.commission_pct:g}% commission" if offer.commission_pct else "",
                   f"{offer.community_discount_pct:g}% discount for her community"
                   if offer.community_discount_pct else "",
                   "a fee can be discussed by a person (never quote one)" if offer.paid_fee else ""]
        terms = "Approved conditions you may state: " + "; ".join(a for a in allowed if a) + "."
    else:
        terms = ("No conditions are approved yet: if she asks about money, gifts or codes, say "
                 "the team will come back to her with a concrete proposal. Never promise anything.")
    prompt = f"""You are {config.persona.name} at {config.persona.company}, answering a fashion
creator who replied to your collaboration proposal.

Her message:
{fence(their_message, "creator reply")}

{UNTRUSTED_RULE}

Write a reply in the language she used (Spanish from Spain with "tú", or French
with "vous"). Under 110 words, plain text, no links, no exclamation marks.
Answer what she asked and nothing else. {terms}
If she asks for her address or size to be used, ask only for what is needed to
send a piece, and say it is used only for that. If she asks how advertising
labelling works, explain it plainly ("Publicidad"/"#publi" in Spain,
"Publicité"/"Collaboration commerciale" in France).

{("FOUNDATIONAL KNOWLEDGE" + chr(10) + skill) if skill else ""}

Return ONLY JSON: {{"subject": "...", "body": "..."}}"""
    data = await brain.think_json(prompt, agent="handler", task="creator_reply")
    if not isinstance(data, dict) or not data.get("body"):
        raise RuntimeError("the model returned no usable reply")
    subject = str(data.get("subject") or ("Re: " + thread_subject if thread_subject else "Re:")).strip()
    body = str(data["body"]).strip()
    issues = [i for i in check_proposal(subject, body, language, offer)
              if not i.startswith("está escrito en")]  # she may write in the other language
    return language, subject, body, issues
