"""Duplicate detection with fictitious creators only."""

from harvey.creators.dedupe import duplicates, find, same_person
from harvey.creators.scoring import Creator


def c(**kw):
    return Creator(**{"handle": "x", **kw})


def test_same_name_or_handle_is_the_same_person():
    assert same_person(c(handle="estilo_ficticio", display_name="Ana Pérez Ficticia"),
                       c(handle="otra", display_name="ana perez ficticia")) == "mismo nombre"
    assert same_person(c(handle="estilo-ficticio"), c(handle="estilo_ficticio")) == "mismo usuario"


def test_a_shared_listing_page_alone_is_not_a_duplicate():
    page = "https://plataforma.example/top/ciudad"
    assert same_person(c(handle="a1", display_name="Ana Ficticia", profile_url=page),
                       c(handle="b2", display_name="Berta Ficticia", profile_url=page)) == ""
    assert same_person(c(handle="a1", display_name="Ana Ficticia", profile_url=page),
                       c(handle="b2", display_name="Ana F.", profile_url=page + "/")) != ""


def test_find_ignores_accents_case_and_separators():
    rows = [{"id": "1", "handle": "maria_ficticia", "creator": c(handle="maria_ficticia",
             display_name="María Ficticia"), "status": "candidate", "updated_at": "2026-10-28"}]
    assert find(rows, "MARIA ficticia") and find(rows, "maría-ficticia") and not find(rows, "otra")
    assert len(duplicates(rows + rows[:1])) == 1
