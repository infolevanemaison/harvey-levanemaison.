from datetime import date

from harvey.creators.search_plan import (
    MAX_SEARCHES,
    Query,
    Use,
    load_log,
    load_templates,
    plan,
    yield_by_type,
)

TODAY = date(2030, 5, 20)


def _q(text, market="ES", kind="prensa"):
    return Query(text, market, kind)


def test_never_used_first_then_platform_before_press_and_es_before_fr():
    templates = [_q("prensa es"), _q("plataforma fr", "FR", "plataforma"),
                 _q("plataforma es", "ES", "plataforma"), _q("usada", "ES", "plataforma")]
    log = [Use(date(2030, 1, 1), "usada", new=1)]
    p = plan(templates, log, TODAY)
    assert [q.text for q in p.today] == ["plataforma es", "plataforma fr", "prensa es", "usada"]


def test_recent_query_waits():
    p = plan([_q("a")], [Use(TODAY, "a", new=2)], TODAY, cooldown_days=14)
    assert p.today == [] and [q.text for q in p.waiting] == ["a"]


def test_query_with_no_new_candidates_twice_is_set_aside():
    log = [Use(date(2030, 1, 1), "a", new=0), Use(date(2030, 2, 1), "a", new=0)]
    p = plan([_q("a"), _q("b")], log, TODAY)
    assert [q.text for q in p.retired] == ["a"] and [q.text for q in p.today] == ["b"]


def test_one_empty_use_is_not_enough_to_retire():
    log = [Use(date(2030, 1, 1), "a", new=3), Use(date(2030, 2, 1), "a", new=0)]
    p = plan([_q("a")], log, TODAY)
    assert [q.text for q in p.today] == ["a"] and p.retired == []


def test_never_more_than_the_daily_limit():
    templates = [_q(f"q{i}") for i in range(20)]
    assert len(plan(templates, [], TODAY, n=50).today) == MAX_SEARCHES


def test_csv_loading_skips_blanks_duplicates_and_bad_dates(tmp_path):
    t = tmp_path / "plantillas.csv"
    t.write_text("consulta,mercado,tipo\nuno,es,plataforma\n,ES,blog\nUNO,FR,prensa\ndos,XX,raro\n",
                 encoding="utf-8")
    templates = load_templates(str(t))
    assert [(q.text, q.market, q.kind) for q in templates] == [("uno", "ES", "plataforma"),
                                                                ("dos", "ES", "prensa")]
    r = tmp_path / "registro.csv"
    r.write_text("fecha,consulta,resultados,nuevas,conocidas,descartadas,motivo\n"
                 "2030-05-01,uno,10,1,3,2,tamaño\nayer,dos,1,1,0,0,\n", encoding="utf-8")
    log = load_log(str(r))
    assert len(log) == 1 and log[0].new == 1 and log[0].reason == "tamaño"
    assert load_log(str(tmp_path / "no-existe.csv")) == []
    assert yield_by_type(templates, log) == {
        "plataforma": {"busquedas": 1, "nuevas": 1, "conocidas": 3, "descartadas": 2}}
