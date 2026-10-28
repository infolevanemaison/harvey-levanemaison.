"""harvey watch: read-only store checks.

  harvey watch queries                      the read queries, to run by hand
  harvey watch check <snapshot.json> --out <dir>
  harvey watch run --out <dir>              fetch with the tokens in the environment

Both write into <dir>: estado.json (state between runs), ultimo.md (digest),
decisiones.md (what waits on the owner) and, only when something new and
important appeared, notificar.md. Nothing is sent anywhere from here.
"""

import json
import os
import sys
from datetime import UTC, datetime


def add_parser(subparsers) -> None:
    sub = subparsers.add_parser("watch", help="Read-only checks on orders, deliveries, catalog and ads")
    sub.add_argument("action", choices=("queries", "check", "run"))
    sub.add_argument("target", nargs="?", default="", help="check: snapshot JSON")
    sub.add_argument("--out", default="vigilancia", help="folder for state and reports")
    sub.add_argument("--max-requests", type=int, default=40, help="run: request cap per run")
    sub.set_defaults(func=cmd_watch)


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def process(snapshot: dict, out: str, now: datetime | None = None, errors=()) -> dict:
    from harvey.watch.alerts import (
        decisions,
        digest,
        load_state,
        save_state,
        should_notify,
        update_state,
    )
    from harvey.watch.checks import run_checks
    now = now or datetime.now(UTC)
    os.makedirs(out, exist_ok=True)
    alerts, unchecked = run_checks(snapshot, now)
    state_path = os.path.join(out, "estado.json")
    state = load_state(state_path)
    change = update_state(state, alerts, now, unchecked)
    report = digest(change, now, unchecked)
    if errors:
        report += "\n## Errores de lectura\n\n" + "\n".join(f"- {e}" for e in errors) + "\n"
    save_state(state, state_path)
    _write(os.path.join(out, "ultimo.md"), report)
    _write(os.path.join(out, "decisiones.md"), decisions(state))
    notify = should_notify(change)
    note = os.path.join(out, "notificar.md")
    if notify or errors:
        lines = [f"- **{a.severity}** · {a.message} → {a.action}" for a in notify]
        lines += [f"- **error de lectura** · {e}" for e in errors]
        _write(note, "# Harvey · vigilancia\n\n" + "\n".join(lines) + "\n")
    elif os.path.exists(note):
        os.remove(note)
    return {"alerts": len(alerts), "new": len(change["new"]), "notify": len(notify),
            "unchecked": list(unchecked), "errors": list(errors)}


def cmd_watch(args) -> None:
    if args.action == "queries":
        from harvey.watch.queries import SHOPIFY_QUERIES
        for name, q in SHOPIFY_QUERIES.items():
            print(f"\n# {name}\n{q}")
        return
    if args.action == "check":
        if not args.target:
            sys.exit("  Uso: harvey watch check <snapshot.json> --out <carpeta>")
        with open(args.target, encoding="utf-8") as f:
            snapshot = json.load(f)
        result = process(snapshot, args.out)
    else:
        from harvey.watch.fetch import Budget, snapshot_from_env
        snapshot, errors = snapshot_from_env(budget=Budget(args.max_requests))
        result = process(snapshot, args.out, errors=errors)
    print(f"\n  Vigilancia: {result['alerts']} alertas, {result['new']} nuevas, "
          f"{result['notify']} para avisar. Informe en {args.out}/ultimo.md")
    if result["unchecked"]:
        print(f"  Sin comprobar: {', '.join(result['unchecked'])}")
    for e in result["errors"]:
        print(f"  ✗ {e}")
    print()
