from datetime import date

from harvey.creators.search_plan import (
    MAX_SEARCHES,
    Query,
    Use,
    check_log,
    load_log,
    load_templates,
    plan,
    query_key,
    reasons_count,
    yield_by_type,
)

TODAY = date(2030, 5, 20)


def _q(text, market="ES", kind="prensa"):
    return Query(text, market, kind)


def test_never_used_first_then_mediakit_before_press_and_es_before_fr():
    templates = [_q("prensa es"), _q("blog fr", "FR", "blog"),
                 _q("kit es", "ES", "mediakit"), _q("usada", "ES", "mediakit")]
    log = [Use(date(2030, 1, 1), "usada", new=1)]
    p = plan(templates, log, TODAY)
    assert [q.text for q in p.today] == ["kit es", "blog fr", "prensa es", "usada"]


def test_recent_query_waits_even_reworded():
    p = plan([_q("Moda «Mujer» 50")], [Use(TODAY, "50 moda MUJER", new=2)], TODAY, cooldown_days=14)
    assert p.today == [] and [q.text for q in p.waiting] == ["Moda «Mujer» 50"]


def test_query_key_ignores_order_case_quotes_and_accents():
    assert query_key('"Mode" femme élégante') == query_key("elegante FEMME mode")


def test_query_with_no_new_candidates_twice_is_set_aside():
    log = [Use(date(2030, 1, 1), "a", new=0), Use(date(2030, 2, 1), "a", new=0)]
    p = plan([_q("a"), _q("b")], log, TODAY)
    assert [q.text for q in p.retired] == ["a"] and [q.text for q in p.today] == ["b"]


def test_one_empty_use_is_not_enough_to_retire():
    log = [Use(date(2030, 1, 1), "a", new=3), Use(date(2030, 2, 1), "a", new=0)]
    p = plan([_q("a")], log, TODAY)
    assert [q.text for q in p.today] == ["a"] and p.retired == []


def test_blocked_source_is_never_picked():
    templates = [_q("site:collabstr.com moda", kind="plataforma"), _q("site:ejemplo.test moda"),
                 _q("blog moda")]
    p = plan(templates, [], TODAY, blocked=("collabstr", "ejemplo.test"))
    assert [q.text for q in p.today] == ["blog moda"] and len(p.blocked) == 2


def test_collabstr_is_blocked_by_default():
    p = plan([_q("Collabstr influencer moda")], [], TODAY)
    assert p.today == [] and len(p.blocked) == 1


def test_france_keeps_its_share():
    templates = [_q(f"es{i}", "ES", "mediakit") for i in range(8)] + [_q("fr1", "FR", "prensa")]
    p = plan(templates, [], TODAY)
    assert len(p.today) == MAX_SEARCHES and "fr1" in [q.text for q in p.today]
    assert sum(q.market == "ES" for q in p.today) == MAX_SEARCHES - 1


def test_never_more_than_the_daily_limit():
    templates = [_q(f"q{i}") for i in range(20)]
    assert len(plan(templates, [], TODAY, n=50).today) == MAX_SEARCHES


def test_check_log_flags_broken_rules():
    run = [Use(TODAY, f"q{i}", run="r1", new=1, reasons=[]) for i in range(7)]
    run.append(Use(TODAY, "site:collabstr.com x", run="r2", reasons=["fuente_no_permitida"]))
    run.append(Use(TODAY, "y", run="r2", sources=["https://www.collabstr.com/x"], reasons=["tamano"]))
    run.append(Use(TODAY, "z", run="r2", reasons=["inventado"]))
    run.append(Use(TODAY, "w", run="r2", duplicates=2, duplicate_ids=["a1"], reasons=["duplicada"]))
    run.append(Use(TODAY, "v", run="r2"))
    text = "\n".join(check_log(run))
    assert "r1: 7 búsquedas" in text and "r1: 7 candidatas nuevas" in text
    assert text.count("fuente excluida") == 2
    assert "motivo desconocido inventado" in text
    assert "2 duplicadas pero 1 ids" in text
    assert "sin candidatas nuevas y sin motivo en «v»" in text


def test_check_log_clean_run():
    log = [Use(TODAY, "a", run="r1", new=1), Use(TODAY, "b", run="r1", duplicates=1,
                                                  duplicate_ids=["abc12345"], reasons=["duplicada"])]
    assert check_log(log) == []


def test_csv_loading_new_and_old_format(tmp_path):
    t = tmp_path / "plantillas.csv"
    t.write_text("consulta,mercado,tipo\nuno,es,mediakit\n,ES,blog\nUNO,FR,prensa\ndos,XX,raro\n",
                 encoding="utf-8")
    templates = load_templates(str(t))
    assert [(q.text, q.market, q.kind) for q in templates] == [("uno", "ES", "mediakit"),
                                                                ("dos", "ES", "prensa")]
    r = tmp_path / "registro.csv"
    r.write_text("fecha,ejecucion,consulta,mercado,resultados,nuevas,duplicadas,ids_duplicadas,"
                 "descartadas,motivos,fuentes\n"
                 "2030-05-01,2030-05-01-1,uno,ES,10,1,2,a1;b2,3,duplicada;tamano,https://blog.example\n"
                 "ayer,,dos,ES,1,1,0,,0,,\n", encoding="utf-8")
    log = load_log(str(r))
    assert len(log) == 1
    u = log[0]
    assert (u.run, u.new, u.duplicates, u.duplicate_ids, u.reasons, u.sources) == (
        "2030-05-01-1", 1, 2, ["a1", "b2"], ["duplicada", "tamano"], ["https://blog.example"])
    old = tmp_path / "antiguo.csv"
    old.write_text("fecha,consulta,resultados,nuevas,conocidas,descartadas,motivo\n"
                   "2030-05-02,dos,4,0,1,0,duplicada\n", encoding="utf-8")
    o = load_log(str(old))[0]
    assert (o.run, o.duplicates, o.reasons) == ("2030-05-02", 1, ["duplicada"])
    assert load_log(str(tmp_path / "no-existe.csv")) == []
    assert yield_by_type(templates, log) == {
        "mediakit": {"busquedas": 1, "nuevas": 1, "duplicadas": 2, "descartadas": 3}}
    assert reasons_count(log + [o]) == {"duplicada": 2, "tamano": 1}
