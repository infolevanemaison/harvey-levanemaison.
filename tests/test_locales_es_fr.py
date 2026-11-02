"""Spanish (Spain) and French (France) outreach: opt-outs in those languages
are honoured, the gate knows their spam and AI-tell phrases, the footer is
written in the outreach language, and discovery asks for local results.

All people and businesses here are fictional.
"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from harvey.agents.handler import _opt_out_reason
from harvey.collectors.discover import (
    DEFAULT_LOCATION_CODE, DiscoveryQuery, _dfs_location, build_queries,
)
from harvey.config import (
    DEFAULT_OPT_OUT_LINE, ComplianceConfig, LocaleConfig, compliance_footer_lines,
)
from harvey.gate import pre_send_check
from harvey.integrations.mail_provider import InboundMessage
from harvey.locales import (
    accept_language, fold, outreach_country, outreach_language, reply_language_rule,
    writing_rules,
)
from tests.test_compliance_footer import ADDRESS, RecordingBrain
from tests.test_outbox_native import (  # noqa: F401  (state is a fixture)
    FakeProvider, make_handler, seed_prospect, state,
)


def _cfg(language="es", country="", formality="informal", opt_out_line=None):
    compliance = (ComplianceConfig(postal_address=ADDRESS) if opt_out_line is None
                  else ComplianceConfig(postal_address=ADDRESS, opt_out_line=opt_out_line))
    return SimpleNamespace(
        locale=LocaleConfig(language=language, country=country, formality=formality),
        compliance=compliance,
        icp=SimpleNamespace(industries=["moda mujer"], geography=["Madrid"],
                            geo_coordinates={}, keyword_variants={}),
        product=SimpleNamespace(name="P"),
    )


# ── Locale basics ──

def test_english_stays_the_default():
    cfg = SimpleNamespace()
    assert outreach_language(cfg) == "en"
    assert outreach_country(cfg) == ""
    assert writing_rules(cfg) == ""
    assert reply_language_rule(cfg) == ""
    assert accept_language(cfg).startswith("en-US")


def test_language_implies_its_country():
    assert outreach_country(_cfg("es")) == "ES"
    assert outreach_country(_cfg("fr")) == "FR"
    assert outreach_country(_cfg("fr", country="BE")) == "BE"


def test_bad_locale_values_are_rejected():
    with pytest.raises(ValidationError):
        LocaleConfig(language="de")
    with pytest.raises(ValidationError):
        LocaleConfig(country="Spain")
    with pytest.raises(ValidationError):
        LocaleConfig(formality="casual")


def test_fold_removes_accents_and_case():
    assert fold("Désinscrivez-MOI") == "desinscrivez-moi"
    assert fold("Última oportunidad") == "ultima oportunidad"


def test_writing_rules_name_the_language_and_register():
    es = writing_rules(_cfg("es", formality="informal"))
    assert "SPANISH" in es and '"tú"' in es
    assert '"usted"' in writing_rules(_cfg("es", formality="formal"))
    fr = writing_rules(_cfg("fr"))
    assert "FRENCH" in fr and '"vous"' in fr
    assert "{{first_name}}" in es


# ── Footer ──

def test_default_footer_is_written_in_the_outreach_language():
    assert compliance_footer_lines(_cfg("es", formality="informal")) == [
        ADDRESS, '¿No te interesa? Responde "baja" y no volveré a escribirte.']
    assert compliance_footer_lines(_cfg("es", formality="formal"))[1].startswith("¿No le interesa?")
    assert compliance_footer_lines(_cfg("fr"))[1].startswith("Pas intéressé(e) ?")
    assert compliance_footer_lines(_cfg("en"))[1] == DEFAULT_OPT_OUT_LINE


def test_a_custom_opt_out_line_is_kept_as_written():
    line = 'Si prefieres no recibir más mensajes, responde "baja".'
    assert compliance_footer_lines(_cfg("es", opt_out_line=line))[1] == line


@pytest.mark.parametrize("line", [
    'Responde "baja" si no quieres más correos.',
    'Si no le interesa, responda «baja».',
    "Répondez « stop » pour ne plus recevoir de message.",
    'Répondez "non merci" et je ne vous écrirai plus.',
])
def test_spanish_and_french_opt_out_lines_are_accepted(line):
    assert ComplianceConfig(opt_out_line=line).opt_out_line == line


def test_an_opt_out_line_without_a_recognised_word_is_rejected():
    with pytest.raises(ValidationError):
        ComplianceConfig(opt_out_line="Si no te interesa, dímelo.")


# ── Opt-out detection ──

@pytest.mark.parametrize("text", [
    "Por favor, darme de baja.",
    "Dadme de baja de vuestra lista",
    "No me escribáis más, gracias.",
    "Dejad de enviarme correos",
    "Borrad mis datos, por favor",
    "No, gracias.",
    "no muchas gracias",
    "Baja",
    "BAJA.",
    "Merci de me désinscrire.",
    "Désabonnez-moi s'il vous plaît",
    "Je ne souhaite plus recevoir vos e-mails, ne plus recevoir.",
    "Ne me contactez plus.",
    "Non merci.",
    "Stop",
    "Arrêt",
])
def test_spanish_and_french_opt_outs_are_honoured(text):
    assert _opt_out_reason(text, text) is not None


@pytest.mark.parametrize("text", [
    "Estoy de baja hasta el lunes, te respondo a la vuelta.",   # sick leave
    "Me encanta la colección, ¿me cuentas más?",
    "¿Por qué no? Gracias por escribir.",
    "No gracias a ti, ha sido un placer.",
    "Oui ou non merci de préciser les tarifs.",
    "Avec plaisir, merci pour votre message.",
])
def test_ordinary_replies_are_not_opt_outs(text):
    assert _opt_out_reason(text, text) is None


async def _reply(state, body, language="es", intent="interested"):
    pid = await seed_prospect(state, email="ana@boutique.example", status="contacted")
    provider = FakeProvider()
    provider.inbound = [InboundMessage(
        provider_id="in1", from_email="ana@boutique.example", subject="Re: hola", body=body)]
    handler = make_handler(state, provider, intent=intent)
    handler.config.compliance = ComplianceConfig(postal_address=ADDRESS)
    handler.config.locale = LocaleConfig(language=language, formality="informal")
    handler.brain = RecordingBrain(intent)
    await handler._run_native()
    return (await state.get_prospect(pid)).status, handler.brain.prompts


@pytest.mark.asyncio
async def test_a_spanish_opt_out_stops_the_prospect_end_to_end(state):
    status, prompts = await _reply(state, "Hola, por favor dadme de baja.")
    assert status == "opted_out"
    assert prompts == []  # no model call, no reply


@pytest.mark.asyncio
async def test_our_own_quoted_spanish_footer_is_not_an_opt_out(state):
    body = ("Me interesa, ¿qué condiciones tenéis?\n\nEl mar, Harvey escribió:\n"
            "> Una nota breve.\n> " + ADDRESS +
            '\n> ¿No te interesa? Responde "baja" y no volveré a escribirte.')
    status, prompts = await _reply(state, body)
    assert status != "opted_out"
    # The reply prompt tells the model to answer in their language.
    assert any("reply in the same language" in p for p in prompts)


@pytest.mark.asyncio
async def test_a_spanish_legal_threat_escalates(state):
    status, prompts = await _reply(state, "Voy a presentar una denuncia ante la AEPD.")
    assert status != "opted_out"
    assert prompts == []  # escalated by keyword, never auto-answered


@pytest.mark.asyncio
async def test_a_french_legal_threat_escalates(state):
    status, prompts = await _reply(state, "Je vais saisir la CNIL.", language="fr")
    assert prompts == []


# ── Pre-send gate ──

@pytest.mark.parametrize("body", [
    "Hola Ana, haz clic aquí para ver la colección.",
    "Hola Ana, haz clic aqui para ver la colección.",
    "Es una oferta exclusiva para ti.",
    "Espero que este correo te encuentre bien. ¿Hablamos?",
    "Bonjour Claire, cliquez ici pour découvrir la collection.",
    "C'est une offre spéciale, sans engagement.",
    "J’espère que ce message vous trouve bien.",
])
def test_gate_blocks_spanish_and_french_spam_phrases(body):
    result = pre_send_check(to_email="ana@boutique.example", subject="colaboración",
                            body=body)
    assert not result.ok
    assert any("banned phrases" in r for r in result.reasons)


def test_gate_lets_a_natural_spanish_email_through():
    body = ("Hola Ana, vi tu último reel con el vestido midi de lino y cómo lo "
            "combinas para el trabajo. ¿Te apetecería probar una pieza de nuestra "
            "nueva colección y contarnos qué te parece?")
    result = pre_send_check(to_email="ana@boutique.example", subject="una idea para ti",
                            body=body)
    assert result.ok, result.reasons


# ── Discovery and scraping locale ──

def test_queries_carry_the_language_and_country():
    (q,) = build_queries(_cfg("es"))
    assert (q.language, q.country) == ("es", "ES")


def test_queries_stay_english_by_default():
    cfg = _cfg("en")
    (q,) = build_queries(cfg)
    assert (q.language, q.country) == ("en", "")
    assert _dfs_location(DiscoveryQuery(term="x"), "1z") == {"location_code": DEFAULT_LOCATION_CODE}


def test_a_countrywide_search_uses_the_country_code():
    assert _dfs_location(DiscoveryQuery(term="x", country="ES"), "1z") == {"location_code": 2724}
    assert _dfs_location(DiscoveryQuery(term="x", country="FR"), "1z") == {"location_code": 2250}


def test_accept_language_follows_the_locale():
    assert accept_language(_cfg("es")).startswith("es-ES")
    assert accept_language(_cfg("fr")).startswith("fr-FR")


# ── Writer ──

@pytest.mark.asyncio
async def test_writer_prompts_ask_for_spanish(tmp_path):
    from harvey.config import LocaleConfig as _Locale
    from tests import test_writer_feedback as wf
    s = wf.StateManager(str(tmp_path / "w.db"))
    await s.init_db()
    pid = await wf.prospect(s, "Lola")

    brain = wf.RecordingBrain({"subject": "hola", "body": "Hola Lola"})
    w = wf.writer(brain, s, "gmail")
    w.config.locale = _Locale(language="es", formality="informal")
    await w._write_personal_email(await s.get_prospect(pid))
    assert "SPANISH AS WRITTEN IN SPAIN" in brain.prompts[0]

    brain = wf.RecordingBrain(wf.SEQ)
    w = wf.writer(brain, s, "instantly")
    w.config.locale = _Locale(language="fr")
    await w._write_sequence([await s.get_prospect(pid)])
    assert "FRENCH AS WRITTEN IN FRANCE" in brain.prompts[0]


@pytest.mark.asyncio
async def test_writer_prompt_is_unchanged_in_english(tmp_path):
    from tests import test_writer_feedback as wf
    s = wf.StateManager(str(tmp_path / "w.db"))
    await s.init_db()
    pid = await wf.prospect(s, "Max")
    brain = wf.RecordingBrain({"subject": "hi", "body": "Hi Max"})
    await wf.writer(brain, s, "gmail")._write_personal_email(await s.get_prospect(pid))
    assert "LANGUAGE —" not in brain.prompts[0]
