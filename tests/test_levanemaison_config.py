"""The Levanemaison configuration template loads and keeps the safe defaults:
nothing is sent without approval, LinkedIn stays off, Spanish locale."""

from pathlib import Path

from harvey.config import compliance_footer_lines, load_config
from harvey.locales import outreach_country, outreach_language

TEMPLATE = Path(__file__).resolve().parent.parent / "levanemaison" / "harvey.levanemaison.example.yaml"


def test_template_loads_with_safe_defaults():
    cfg = load_config(str(TEMPLATE))
    assert cfg.channels.email.require_approval is True
    assert cfg.channels.linkedin.enabled is False
    assert cfg.channels.email.max_daily_sends <= 10
    assert cfg.compliance.precleared.enabled is False
    assert cfg.usage.quiet_hours.timezone == "Europe/Madrid"
    assert (outreach_language(cfg), outreach_country(cfg)) == ("es", "ES")


def test_template_footer_is_spanish():
    cfg = load_config(str(TEMPLATE))
    assert compliance_footer_lines(cfg)[-1] == (
        '¿No te interesa? Responde "baja" y no volveré a escribirte.')


def test_template_has_no_secrets():
    text = TEMPLATE.read_text(encoding="utf-8").lower()
    for word in ("api_key:", "password:", "secret:", "token:"):
        assert word not in text
