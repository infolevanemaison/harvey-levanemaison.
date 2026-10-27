"""Outreach language and country: English, Spanish (Spain) or French (France).

Harvey was written for English cold email. A Spanish or French operator
needs more than a translated prompt: replies that opt out in their own
language must be honoured, the pre-send gate must know the local spam and
AI-tell phrases, search engines must be asked for local results, and the
footer must ask for an opt-out word Harvey recognises in that language.
Everything language-specific lives here so the rest of the code asks one
place. The default ("en", no country) changes nothing for existing users.
"""

import unicodedata

SUPPORTED_LANGUAGES = ("en", "es", "fr")

LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish as written in Spain (es-ES)",
    "fr": "French as written in France (fr-FR)",
}

# What scout sends as Accept-Language, so a bilingual site serves the
# version a local buyer would read.
ACCEPT_LANGUAGE = {
    "en": "en-US,en;q=0.9",
    "es": "es-ES,es;q=0.9,en;q=0.5",
    "fr": "fr-FR,fr;q=0.9,en;q=0.5",
}

# DataForSEO location codes for a search with no city: the country itself.
DATAFORSEO_COUNTRY_CODES = {
    "US": 2840,
    "ES": 2724,
    "FR": 2250,
    "GB": 2826,
    "BE": 2056,
    "CH": 2756,
    "PT": 2620,
    "IT": 2380,
}

# The country a language implies when none is set.
DEFAULT_COUNTRY = {"en": "", "es": "ES", "fr": "FR"}

# Footer lines used when compliance.opt_out_line is left at Harvey's English
# default. Each asks for a word the Handler always honours on its own.
DEFAULT_OPT_OUT_LINES = {
    ("es", "informal"): '¿No te interesa? Responde "baja" y no volveré a escribirte.',
    ("es", "formal"): '¿No le interesa? Responda "baja" y no volveré a escribirle.',
    # French business email is "vous" whatever the register.
    ("fr", "informal"): 'Pas intéressé(e) ? Répondez "stop" et je ne vous écrirai plus.',
    ("fr", "formal"): 'Pas intéressé(e) ? Répondez "stop" et je ne vous écrirai plus.',
}


def fold(text: str) -> str:
    """Lowercase without accents: "Désinscrivez-MOI" -> "desinscrivez-moi".

    People type opt-outs on phones, with and without accents, so matching
    compares folded text against folded phrases.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _locale(config):
    return getattr(config, "locale", None)


def outreach_language(config) -> str:
    """The configured outreach language: "en", "es" or "fr"."""
    loc = _locale(config)
    lang = (getattr(loc, "language", "") or "en").lower()
    return lang if lang in SUPPORTED_LANGUAGES else "en"


def outreach_country(config) -> str:
    """Two-letter country of the prospects, or "" when not set."""
    loc = _locale(config)
    country = (getattr(loc, "country", "") or "").upper()
    return country or DEFAULT_COUNTRY.get(outreach_language(config), "")


def formality(config) -> str:
    loc = _locale(config)
    value = (getattr(loc, "formality", "") or "formal").lower()
    return value if value in ("formal", "informal") else "formal"


def accept_language(config) -> str:
    return ACCEPT_LANGUAGE[outreach_language(config)]


def dataforseo_language_code(config) -> str:
    return outreach_language(config)


def default_opt_out_line(config) -> str:
    """The localized footer opt-out line, or "" for English."""
    lang = outreach_language(config)
    if lang == "en":
        return ""
    return DEFAULT_OPT_OUT_LINES[(lang, formality(config))]


def writing_rules(config) -> str:
    """Extra instructions for writing in Spanish or French, or "" for English.

    The English rules in prompts/writer.md still apply: these say which
    language to write in and give the local equivalents of the banned
    phrases, so the model doesn't translate English habits word for word.
    """
    lang = outreach_language(config)
    if lang == "en":
        return ""
    if lang == "es":
        register = (
            'Use "tú" (never "vosotros" to one person). Warm and direct, like a '
            "person who runs a small fashion brand writing herself."
            if formality(config) == "informal" else
            'Use "usted". Courteous and direct, never stiff or bureaucratic.'
        )
        local = """- Spanish from Spain: "vale", "móvil", "ordenador", never Latin American forms.
- Opening question marks are correct (¿...?). Still at most one question.
- Never write calques of English sales filler: "espero que este correo te encuentre bien",
  "quería ponerme en contacto contigo", "solo quería", "llevar al siguiente nivel",
  "sin compromiso", "oferta exclusiva", "haz clic aquí", "no te lo pierdas", "última oportunidad".
- No spam words: "gratis", "oferta", "descuento", "% de descuento", "urgente", "compra ya"."""
    else:
        register = (
            'Always "vous". Elegant and simple, like a small French-speaking '
            "fashion brand writing itself, never like a marketing agency."
        )
        local = """- French from France. Typographic spaces before "?" and ":" are fine; no em dashes.
- Never write calques of English sales filler: "j'espère que ce message vous trouve bien",
  "je me permets de vous contacter", "je voulais juste", "passer au niveau supérieur",
  "sans engagement", "offre exclusive", "cliquez ici", "ne manquez pas", "dernière chance".
- No spam words: "gratuit", "offre", "promotion", "remise", "urgent", "achetez maintenant"."""
    return f"""

LANGUAGE — WRITE EVERY SUBJECT AND BODY IN {LANGUAGE_NAMES[lang].upper()}:
- Write natively in this language, as a native speaker would. Do not translate from English.
- {register}
{local}
- Every STRICT EMAIL RULE above still applies (word limits count words in this language).
- Keep merge variables exactly as written: {{{{first_name}}}}, {{{{company}}}}, {{{{title}}}}.
"""


def reply_language_rule(config) -> str:
    """Instruction for replies: answer in the language they wrote in."""
    lang = outreach_language(config)
    if lang == "en":
        return ""
    return (
        "\n\nLANGUAGE: reply in the same language the person wrote in. If you "
        f"can't tell, write in {LANGUAGE_NAMES[lang]}. Write natively, never a "
        "word-for-word translation from English.\n"
    )
