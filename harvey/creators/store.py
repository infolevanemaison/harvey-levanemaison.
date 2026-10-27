"""Local storage for creators, proposals and collaboration results.

A separate SQLite file (data/creators.db, gitignored with the rest of data/)
so the creator module never touches the schema of Harvey's pipeline
database. Plain sqlite3: these are short, human-paced operations run from
the command line.

Statuses a person moves a creator through:

  candidate -> approved (for contact) -> drafted -> contacted -> replied
            -> negotiating -> collaborating -> measured
  any       -> rejected | opted_out   (opted_out is permanent)
"""

import csv
import json
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harvey.creators.scoring import Creator, score_creator
from harvey.paths import PROJECT_ROOT

DEFAULT_DB = PROJECT_ROOT / "data" / "creators.db"

CREATOR_STATUSES = ("candidate", "approved", "drafted", "contacted", "replied",
                    "negotiating", "collaborating", "measured", "rejected", "opted_out")
PROPOSAL_STATUSES = ("pending_review", "approved", "rejected", "drafted", "sent")
PROPOSAL_KINDS = ("first", "followup", "reply")
COLLAB_STATUSES = ("agreed", "shipped", "published", "measured", "closed", "cancelled")
# Candidates nobody approved are deleted after this long (data minimisation).
CANDIDATE_RETENTION_DAYS = 180

SCHEMA = """
CREATE TABLE IF NOT EXISTS creators (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    handle TEXT NOT NULL,
    data_json TEXT NOT NULL,
    score INTEGER DEFAULT 0,
    verdict TEXT DEFAULT '',
    score_json TEXT DEFAULT '{}',
    status TEXT DEFAULT 'candidate',
    legal_basis TEXT DEFAULT 'interes legitimo: contacto profesional publicado por ella',
    notes TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(platform, handle)
);
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    creator_id TEXT NOT NULL,
    language TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT DEFAULT 'pending_review',
    issues_json TEXT DEFAULT '[]',
    draft_ref TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS collaborations (
    id TEXT PRIMARY KEY,
    creator_id TEXT NOT NULL,
    status TEXT DEFAULT 'agreed',
    terms_json TEXT DEFAULT '{}',
    code TEXT DEFAULT '',
    link TEXT DEFAULT '',
    shipped_on TEXT DEFAULT '',
    content_due TEXT DEFAULT '',
    post_urls TEXT DEFAULT '',
    labelled_as_ad INTEGER,
    notes TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS inbox_seen (
    message_id TEXT PRIMARY KEY,
    seen_at TEXT
);
CREATE TABLE IF NOT EXISTS results (
    creator_id TEXT NOT NULL,
    period TEXT NOT NULL,
    sessions INTEGER DEFAULT 0,
    orders INTEGER DEFAULT 0,
    net_sales REAL DEFAULT 0,
    gift_cost REAL DEFAULT 0,
    fee REAL DEFAULT 0,
    PRIMARY KEY (creator_id, period)
);
"""

INT_FIELDS = {"followers", "posts_last_30d", "sponsored_posts_last_30d", "comment_quality"}
FLOAT_FIELDS = {"avg_likes", "avg_comments", "avg_views", "follower_growth_30d_pct",
                "audience_female_pct", "audience_35_65_pct", "audience_target_country_pct",
                "quoted_fee_eur"}
OPTIONAL_FIELDS = {"follower_growth_30d_pct", "audience_female_pct", "audience_35_65_pct",
                   "audience_target_country_pct", "comment_quality", "quoted_fee_eur"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _number(field: str, raw: str):
    """A number as people type it: "12.000" and "12,000" are twelve thousand,
    "3,5" and "3.5" three and a half, "12k" twelve thousand, "45%" 45."""
    raw = (raw or "").strip().lower().replace("%", "").replace(" ", "").replace("\u00a0", "")
    if not raw:
        return None if field in OPTIONAL_FIELDS else 0
    scale = 1
    if raw.endswith("k"):
        raw, scale = raw[:-1], 1_000
    elif raw.endswith("m"):
        raw, scale = raw[:-1], 1_000_000
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
        raw = raw.replace(".", "")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+", raw):
        raw = raw.replace(",", "")
    else:
        raw = raw.replace(",", ".")
    value = float(raw) * scale
    return int(value) if field in INT_FIELDS else value


def creator_from_row(row: dict) -> Creator:
    """A Creator from one CSV row; unknown columns are ignored."""
    known = Creator.__dataclass_fields__
    data = {}
    for key, value in row.items():
        key = (key or "").strip()
        if key not in known:
            continue
        if key in INT_FIELDS or key in FLOAT_FIELDS:
            data[key] = _number(key, value)
        else:
            data[key] = (value or "").strip()
    if not data.get("handle"):
        raise ValueError("every row needs a handle")
    data["handle"] = data["handle"].lstrip("@").lower()
    data["platform"] = (data.get("platform") or "instagram").lower()
    data["country"] = (data.get("country") or "").upper()
    data["language"] = (data.get("language") or "").lower()
    return Creator(**data)


class CreatorStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._db()) as db:
            db.executescript(SCHEMA)
            # Columns added after the first release of this file.
            for ddl in ("ALTER TABLE proposals ADD COLUMN kind TEXT DEFAULT 'first'",
                        "ALTER TABLE proposals ADD COLUMN reply_to TEXT DEFAULT ''",
                        "ALTER TABLE proposals ADD COLUMN sent_on TEXT DEFAULT ''"):
                try:
                    db.execute(ddl)
                except sqlite3.OperationalError:
                    pass  # already there
            db.commit()

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    # ── Creators ──

    def upsert(self, creator: Creator, config=None) -> tuple[str, bool]:
        """Add or refresh a creator and score her. A creator who opted out
        or was rejected keeps that status. Returns (id, created)."""
        settings = getattr(config, "creators", None)
        score = score_creator(
            creator,
            countries=tuple(getattr(settings, "countries", ("ES", "FR"))),
            min_followers=getattr(settings, "min_followers", 2_000),
            max_followers=getattr(settings, "max_followers", 150_000),
        )
        now = _now()
        with closing(self._db()) as db:
            found = db.execute("SELECT id FROM creators WHERE platform = ? AND handle = ?",
                               (creator.platform, creator.handle)).fetchone()
            if found:
                db.execute(
                    "UPDATE creators SET data_json = ?, score = ?, verdict = ?, score_json = ?, "
                    "updated_at = ? WHERE id = ?",
                    (json.dumps(creator.to_dict()), score.total, score.verdict,
                     json.dumps(score.to_dict()), now, found["id"]))
                db.commit()
                return found["id"], False
            cid = uuid.uuid4().hex[:8]
            db.execute(
                "INSERT INTO creators (id, platform, handle, data_json, score, verdict, "
                "score_json, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (cid, creator.platform, creator.handle, json.dumps(creator.to_dict()),
                 score.total, score.verdict, json.dumps(score.to_dict()), "candidate", now, now))
            db.commit()
            return cid, True

    def import_csv(self, path: str | Path, config=None) -> dict:
        added = updated = 0
        errors = []
        with open(path, newline="", encoding="utf-8-sig") as f:
            for n, row in enumerate(csv.DictReader(f), start=2):
                try:
                    cid, created = self.upsert(creator_from_row(row), config)
                except (ValueError, TypeError) as e:
                    errors.append(f"line {n}: {e}")
                    continue
                # A backup made with `export` carries each creator's status:
                # an opt-out or a decision must survive a new session.
                saved = (row.get("status") or "").strip()
                if saved in CREATOR_STATUSES and saved != "candidate":
                    current = self.get(cid)["status"]
                    if current != "opted_out":
                        self.set_status(cid, saved)
                added += created
                updated += not created
        return {"added": added, "updated": updated, "errors": errors}

    def get(self, cid: str) -> dict | None:
        with closing(self._db()) as db:
            row = db.execute("SELECT * FROM creators WHERE id = ?", (cid,)).fetchone()
        return self._row(row) if row else None

    def list_creators(self, status: str = "") -> list[dict]:
        sql, args = "SELECT * FROM creators", ()
        if status:
            sql, args = sql + " WHERE status = ?", (status,)
        with closing(self._db()) as db:
            rows = db.execute(sql + " ORDER BY score DESC, handle", args).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row) -> dict:
        out = dict(row)
        out["creator"] = Creator(**json.loads(out.pop("data_json")))
        out["score_detail"] = json.loads(out.pop("score_json") or "{}")
        return out

    def set_status(self, cid: str, status: str, notes: str = "") -> None:
        if status not in CREATOR_STATUSES:
            raise ValueError(f"unknown status {status!r}")
        current = self.get(cid)
        if current is None:
            raise KeyError(cid)
        if current["status"] == "opted_out" and status != "opted_out":
            raise ValueError("this creator opted out: her status can't change")
        with closing(self._db()) as db:
            db.execute("UPDATE creators SET status = ?, notes = CASE WHEN ? = '' THEN notes "
                       "ELSE ? END, updated_at = ? WHERE id = ?",
                       (status, notes, notes, _now(), cid))
            db.commit()

    def forget(self, cid: str) -> None:
        """Delete everything about a creator (right to erasure). Keeps only
        her handle as opted_out, so she is never added and contacted again."""
        current = self.get(cid)
        if current is None:
            raise KeyError(cid)
        stub = Creator(handle=current["handle"], platform=current["platform"])
        with closing(self._db()) as db:
            db.execute("DELETE FROM proposals WHERE creator_id = ?", (cid,))
            db.execute("DELETE FROM collaborations WHERE creator_id = ?", (cid,))
            db.execute("DELETE FROM results WHERE creator_id = ?", (cid,))
            db.execute("UPDATE creators SET data_json = ?, score_json = '{}', score = 0, "
                       "verdict = '', status = 'opted_out', notes = '', updated_at = ? "
                       "WHERE id = ?", (json.dumps(stub.to_dict()), _now(), cid))
            db.commit()

    def purge_stale_candidates(self, days: int = CANDIDATE_RETENTION_DAYS) -> int:
        cutoff = (datetime.now(timezone.utc).replace(tzinfo=None)
                  - timedelta(days=days)).isoformat(timespec="seconds")
        with closing(self._db()) as db:
            cur = db.execute("DELETE FROM creators WHERE status IN ('candidate', 'rejected') "
                             "AND updated_at < ?", (cutoff,))
            db.commit()
            return cur.rowcount

    # ── Proposals ──

    def add_proposal(self, cid: str, language: str, subject: str, body: str,
                     issues: list[str], kind: str = "first", reply_to: str = "") -> str:
        """kind: first (the opening message), followup (the one reminder) or
        reply (an answer to something she wrote; reply_to is her message id)."""
        if kind not in PROPOSAL_KINDS:
            raise ValueError(f"unknown proposal kind {kind!r}")
        pid = uuid.uuid4().hex[:8]
        now = _now()
        with closing(self._db()) as db:
            db.execute(
                "INSERT INTO proposals (id, creator_id, language, subject, body, status, "
                "issues_json, kind, reply_to, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (pid, cid, language, subject, body, "pending_review", json.dumps(issues),
                 kind, reply_to, now, now))
            db.commit()
        return pid

    def get_proposal(self, pid: str) -> dict | None:
        with closing(self._db()) as db:
            row = db.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
        if not row:
            return None
        out = dict(row)
        out["issues"] = json.loads(out.pop("issues_json") or "[]")
        return out

    def list_proposals(self, status: str = "") -> list[dict]:
        sql, args = "SELECT id FROM proposals", ()
        if status:
            sql, args = sql + " WHERE status = ?", (status,)
        with closing(self._db()) as db:
            ids = [r["id"] for r in db.execute(sql + " ORDER BY created_at", args)]
        return [self.get_proposal(i) for i in ids]

    def set_proposal_status(self, pid: str, status: str, draft_ref: str = "") -> None:
        if status not in PROPOSAL_STATUSES:
            raise ValueError(f"unknown proposal status {status!r}")
        with closing(self._db()) as db:
            cur = db.execute(
                "UPDATE proposals SET status = ?, draft_ref = CASE WHEN ? = '' THEN draft_ref "
                "ELSE ? END, updated_at = ? WHERE id = ?",
                (status, draft_ref, draft_ref, _now(), pid))
            db.commit()
            if cur.rowcount != 1:
                raise KeyError(pid)

    def edit_proposal(self, pid: str, subject: str, body: str, issues: list[str]) -> None:
        """A person's edit. It goes back to review: the edited text is what
        gets approved, never the text approved before."""
        with closing(self._db()) as db:
            db.execute("UPDATE proposals SET subject = ?, body = ?, issues_json = ?, "
                       "status = 'pending_review', updated_at = ? WHERE id = ?",
                       (subject, body, json.dumps(issues), _now(), pid))
            db.commit()

    def mark_sent(self, pid: str, on: str = "") -> None:
        """A person sent the draft from Gmail. Only now has she been contacted."""
        proposal = self.get_proposal(pid)
        if proposal is None:
            raise KeyError(pid)
        if proposal["status"] != "drafted":
            raise ValueError(f"proposal {pid} is {proposal['status']}, not a Gmail draft")
        day = on or _now()[:10]
        with closing(self._db()) as db:
            db.execute("UPDATE proposals SET status = 'sent', sent_on = ?, updated_at = ? "
                       "WHERE id = ?", (day, _now(), pid))
            db.commit()
        if self.get(proposal["creator_id"])["status"] in ("approved", "drafted"):
            self.set_status(proposal["creator_id"], "contacted")

    # ── Collaborations ──

    def add_collaboration(self, cid: str, terms: dict, code: str = "", link: str = "",
                          content_due: str = "") -> str:
        """A collaboration both sides agreed to. terms is what was agreed
        (pieces, value, commission, fee) in a person's words and numbers."""
        row = self.get(cid)
        if row is None:
            raise KeyError(cid)
        if row["status"] in ("opted_out", "rejected"):
            raise ValueError(f"the creator is {row['status']}")
        kid = uuid.uuid4().hex[:8]
        now = _now()
        with closing(self._db()) as db:
            db.execute(
                "INSERT INTO collaborations (id, creator_id, status, terms_json, code, link, "
                "content_due, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (kid, cid, "agreed", json.dumps(terms, ensure_ascii=False), code, link,
                 content_due, now, now))
            db.commit()
        self.set_status(cid, "collaborating")
        return kid

    def update_collaboration(self, kid: str, **fields) -> None:
        allowed = {"status", "code", "link", "shipped_on", "content_due", "post_urls",
                   "labelled_as_ad", "notes"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown field(s): {', '.join(sorted(bad))}")
        if "status" in fields and fields["status"] not in COLLAB_STATUSES:
            raise ValueError(f"unknown collaboration status {fields['status']!r}")
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with closing(self._db()) as db:
            cur = db.execute(f"UPDATE collaborations SET {sets}, updated_at = ? WHERE id = ?",
                             (*fields.values(), _now(), kid))
            db.commit()
            if cur.rowcount != 1:
                raise KeyError(kid)

    def collaborations(self, status: str = "") -> list[dict]:
        sql, args = "SELECT * FROM collaborations", ()
        if status:
            sql, args = sql + " WHERE status = ?", (status,)
        with closing(self._db()) as db:
            rows = [dict(r) for r in db.execute(sql + " ORDER BY created_at", args)]
        for r in rows:
            r["terms"] = json.loads(r.pop("terms_json") or "{}")
        return rows

    # ── Inbox ──

    def find_by_email(self, email: str) -> dict | None:
        """The creator whose professional contact is this address."""
        email = (email or "").strip().lower()
        if not email:
            return None
        for row in self.list_creators():
            if (row["creator"].pro_contact_email or "").strip().lower() == email:
                return row
        return None

    def seen(self, message_id: str) -> bool:
        with closing(self._db()) as db:
            return db.execute("SELECT 1 FROM inbox_seen WHERE message_id = ?",
                              (message_id,)).fetchone() is not None

    def mark_seen(self, message_id: str) -> None:
        with closing(self._db()) as db:
            db.execute("INSERT OR IGNORE INTO inbox_seen (message_id, seen_at) VALUES (?, ?)",
                       (message_id, _now()))
            db.commit()

    # ── Results ──

    def record_result(self, cid: str, period: str, sessions=0, orders=0, net_sales=0.0,
                      gift_cost=0.0, fee=0.0) -> None:
        with closing(self._db()) as db:
            db.execute(
                "INSERT INTO results (creator_id, period, sessions, orders, net_sales, gift_cost, "
                "fee) VALUES (?,?,?,?,?,?,?) ON CONFLICT(creator_id, period) DO UPDATE SET "
                "sessions = excluded.sessions, orders = excluded.orders, "
                "net_sales = excluded.net_sales, gift_cost = excluded.gift_cost, fee = excluded.fee",
                (cid, period, int(sessions), int(orders), float(net_sales), float(gift_cost),
                 float(fee)))
            db.commit()

    def results(self, period: str = "") -> list[dict]:
        sql, args = "SELECT * FROM results", ()
        if period:
            sql, args = sql + " WHERE period = ?", (period,)
        with closing(self._db()) as db:
            return [dict(r) for r in db.execute(sql + " ORDER BY creator_id", args)]
