"""Keep the creators store in a folder that a private git repository holds.

The cloud machine Harvey runs on is wiped between sessions, so the SQLite
file can't be the place the data lives. Instead every table is written as
one sorted JSON file (diffable, mergeable by hand) plus a manifest with
row counts and SHA-256 hashes, and read back from there at the start of
the next session.

Only the store's tables go out. Nothing from the configuration, no keys, no
tokens: the dump refuses a folder that holds files that look like secrets.
"""

import hashlib
import json
from contextlib import closing
from pathlib import Path

FORMAT_VERSION = 1
TABLES = {
    "creators": ("id",),
    "proposals": ("id",),
    "collaborations": ("id",),
    "inbox_seen": ("message_id",),
    "results": ("creator_id", "period"),
}
MANIFEST = "manifiesto.json"
SECRET_NAMES = (".env", "credentials.json", "token.json", "harvey.local.yaml", "client_secret")


class BackupError(ValueError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rows(store, table: str) -> list[dict]:
    keys = TABLES[table]
    with closing(store._db()) as db:
        rows = [dict(r) for r in db.execute(f"SELECT * FROM {table}")]
    return sorted(rows, key=lambda r: tuple(str(r.get(k, "")) for k in keys))


def _encode(rows: list[dict]) -> bytes:
    return (json.dumps(rows, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def _refuse_secrets(folder: Path) -> None:
    found = [p.name for p in folder.rglob("*") if p.is_file()
             and any(s in p.name.lower() for s in SECRET_NAMES)]
    if found:
        raise BackupError(f"la carpeta contiene archivos que parecen credenciales: {found}")


def dump(store, folder) -> dict:
    """Write every table to folder/<table>.json and the manifest. Returns it."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _refuse_secrets(folder)
    # No timestamp: the same data must give the same bytes, so a backup with
    # nothing new is not a commit. Git already records when each copy was made.
    manifest = {"formato": FORMAT_VERSION, "tablas": {}}
    for table in TABLES:
        rows = _rows(store, table)
        data = _encode(rows)
        (folder / f"{table}.json").write_bytes(data)
        manifest["tablas"][table] = {"filas": len(rows), "sha256": _sha(data)}
    (folder / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                   encoding="utf-8")
    return manifest


def read(folder) -> dict[str, list[dict]]:
    """The tables in folder, after checking each file against the manifest."""
    folder = Path(folder)
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BackupError(f"no hay {MANIFEST} en {folder}") from None
    if manifest.get("formato") != FORMAT_VERSION:
        raise BackupError(f"formato {manifest.get('formato')} no soportado")
    tables = {}
    for table, meta in manifest["tablas"].items():
        if table not in TABLES:
            raise BackupError(f"tabla desconocida en la copia: {table}")
        data = (folder / f"{table}.json").read_bytes()
        if _sha(data) != meta["sha256"]:
            raise BackupError(f"{table}.json no coincide con el manifiesto (archivo alterado o incompleto)")
        tables[table] = json.loads(data)
        if len(tables[table]) != meta["filas"]:
            raise BackupError(f"{table}.json: {len(tables[table])} filas, el manifiesto dice {meta['filas']}")
    return tables


def restore(store, folder) -> dict[str, int]:
    """Replace the store's content with the copy in folder, all or nothing."""
    tables = read(folder)
    counts = {}
    with closing(store._db()) as db:
        with db:  # one transaction: a failure leaves the store as it was
            for table, rows in tables.items():
                columns = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
                db.execute(f"DELETE FROM {table}")
                for row in rows:
                    cols = [c for c in columns if c in row]
                    db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
                               f"({', '.join('?' for _ in cols)})", [row[c] for c in cols])
                counts[table] = len(rows)
    return counts


def matches(store, folder) -> dict[str, bool]:
    """Per table: is the store exactly what the copy in folder says?"""
    tables = read(folder)
    return {t: _encode(_rows(store, t)) == _encode(tables.get(t, [])) for t in TABLES}
