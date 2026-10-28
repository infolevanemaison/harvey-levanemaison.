"""The creators store survives a wiped machine through a folder of JSON files."""

import json

import pytest

from harvey.creators import sync
from harvey.creators.scoring import Creator
from harvey.creators.store import CreatorStore


def filled(tmp_path, name="a.db"):
    store = CreatorStore(tmp_path / name)
    cid, _ = store.upsert(Creator(handle="estilo_ficticio", country="ES", followers=12_000,
                                  pro_contact_email="colabora@ficticia.example",
                                  pro_contact_source="https://ficticia.example/contacto"))
    store.set_status(cid, "approved")
    pid = store.add_proposal(cid, "es", "Hola", "Cuerpo de prueba", [])
    store.set_proposal_status(pid, "drafted", draft_ref="draft:ficticio")
    store.mark_seen("msg-ficticio-1")
    store.record_result(cid, "2026-11", sessions=40, orders=1, net_sales=54.95)
    return store, cid


def test_dump_then_restore_into_an_empty_store_is_identical(tmp_path):
    store, cid = filled(tmp_path)
    folder = tmp_path / "repo-privado"
    sync.dump(store, folder)
    fresh = CreatorStore(tmp_path / "nueva.db")
    counts = sync.restore(fresh, folder)
    assert counts["creators"] == 1 and counts["proposals"] == 1 and counts["results"] == 1
    assert all(sync.matches(fresh, folder).values())
    assert fresh.get(cid)["status"] == "approved"
    assert fresh.seen("msg-ficticio-1")


def test_an_update_round_trips_and_the_dump_is_deterministic(tmp_path):
    store, cid = filled(tmp_path)
    folder = tmp_path / "repo-privado"
    sync.dump(store, folder)
    first = (folder / "creators.json").read_bytes()
    sync.dump(store, folder)
    assert (folder / "creators.json").read_bytes() == first      # no noise in git diffs
    store.set_status(cid, "contacted")
    sync.dump(store, folder)
    other = CreatorStore(tmp_path / "otra.db")
    sync.restore(other, folder)
    assert other.get(cid)["status"] == "contacted"


def test_a_tampered_or_truncated_copy_is_refused_and_nothing_changes(tmp_path):
    store, cid = filled(tmp_path)
    folder = tmp_path / "repo-privado"
    sync.dump(store, folder)
    rows = json.loads((folder / "creators.json").read_text(encoding="utf-8"))
    (folder / "creators.json").write_text(json.dumps(rows[:0]), encoding="utf-8")
    target, _ = filled(tmp_path, "destino.db")
    with pytest.raises(sync.BackupError):
        sync.restore(target, folder)
    assert target.list_creators()                                 # untouched


def test_secrets_next_to_the_copy_are_refused(tmp_path):
    store, _ = filled(tmp_path)
    folder = tmp_path / "repo-privado"
    folder.mkdir()
    (folder / ".env").write_text("CLAVE=no", encoding="utf-8")
    with pytest.raises(sync.BackupError):
        sync.dump(store, folder)


def test_the_cli_refuses_a_folder_inside_the_public_repo(tmp_path):
    from types import SimpleNamespace
    from harvey.creators.cli import cmd_creators
    from harvey.paths import PROJECT_ROOT
    args = SimpleNamespace(action="backup", target=str(PROJECT_ROOT / "datos"), db=str(tmp_path / "x.db"),
                           status="", export=False, ref="", month="", text="", text_file="",
                           message_id="", terms="", due="", path="", fields=[])
    with pytest.raises(SystemExit, match="público"):
        cmd_creators(args)


def test_a_backup_with_nothing_new_writes_the_same_bytes(tmp_path):
    store, _ = filled(tmp_path)
    folder = tmp_path / "repo-privado"
    sync.dump(store, folder)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    sync.dump(store, folder)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
