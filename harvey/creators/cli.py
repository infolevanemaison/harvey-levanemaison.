"""`harvey creators ...`: the creator module from the command line.

Every step that reaches a person is a separate command a human runs (or
asks Claude to run): approve a creator, approve a proposal, create the
draft. Nothing here sends email.
"""

import argparse
import asyncio
import csv
import json
import sys

from harvey.creators.store import CreatorStore

ACTIONS = ("import", "export", "list", "show", "approve", "reject", "forget", "propose", "proposals",
           "show-proposal", "approve-proposal", "reject-proposal", "draft", "mark-drafted", "link",
           "report", "queries", "purge")


def add_parser(subparsers) -> None:
    sub = subparsers.add_parser(
        "creators", help="Evaluate creators and prepare collaboration proposals (drafts only)")
    sub.add_argument("action", choices=ACTIONS)
    sub.add_argument("target", nargs="?", default="",
                     help="a CSV file, a creator id or a proposal id, depending on the action")
    sub.add_argument("--status", default="", help="filter list/proposals by status")
    sub.add_argument("--export", action="store_true",
                     help="draft: print the checked draft as JSON for the Gmail connector")
    sub.add_argument("--ref", default="", help="mark-drafted: the Gmail draft id from the connector")
    sub.add_argument("--month", default="", help="link/report: YYYY-MM")
    sub.add_argument("--path", default="", help="link: landing path, e.g. collections/vestidos")
    sub.add_argument("--db", default="", help=argparse.SUPPRESS)
    sub.set_defaults(func=cmd_creators)


def _config():
    from harvey.config import load_config
    return load_config()


def _store(args) -> CreatorStore:
    return CreatorStore(args.db) if args.db else CreatorStore()


def _need(args, what: str) -> str:
    if not args.target:
        print(f"\n  Falta {what}.\n")
        sys.exit(2)
    return args.target


def _print_creator(row: dict) -> None:
    c, s = row["creator"], row["score_detail"]
    print(f"\n  [{row['id']}] @{c.handle} ({c.platform}, {c.country or '?'})  "
          f"{row['score']}/100 · {row['verdict']} · estado: {row['status']}")
    if s:
        print(f"    audiencia {s['audience']}/35 · interacción {s['engagement']}/25 · "
              f"autenticidad {s['authenticity']}/25 · coste {s['cost']}/15")
        for r in s.get("reasons", []):
            print(f"    + {r}")
        for w in s.get("warnings", []):
            print(f"    ! {w}")


def cmd_creators(args) -> None:
    store = _store(args)
    action = args.action

    if action == "import":
        result = store.import_csv(_need(args, "el archivo CSV"), _config())
        print(f"\n  {result['added']} añadidas, {result['updated']} actualizadas.")
        for e in result["errors"]:
            print(f"  ✗ {e}")
        print("  Siguiente: harvey creators list\n")
        return

    if action == "export":
        # Back up the list before the cloud session ends. Personal data: keep
        # the file in your own storage, never in the repository.
        from dataclasses import fields
        from harvey.creators.scoring import Creator
        path = _need(args, "el archivo CSV de salida")
        names = [f.name for f in fields(Creator)]
        rows = store.list_creators(args.status)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=names + ["status"])
            writer.writeheader()
            for row in rows:
                writer.writerow({**row["creator"].to_dict(), "status": row["status"]})
        print(f"\n  {len(rows)} creadoras exportadas a {path}. Guárdalo fuera del repositorio.\n")
        return

    if action == "list":
        rows = store.list_creators(args.status)
        if not rows:
            print("\n  No hay creadoras todavía.\n")
        for row in rows:
            _print_creator(row)
        print()
        return

    if action == "show":
        row = store.get(_need(args, "el id de la creadora"))
        if not row:
            sys.exit(f"  No existe {args.target}")
        _print_creator(row)
        print("\n" + json.dumps(row["creator"].to_dict(), ensure_ascii=False, indent=2) + "\n")
        return

    if action in ("approve", "reject"):
        cid = _need(args, "el id de la creadora")
        store.set_status(cid, "approved" if action == "approve" else "rejected")
        print(f"\n  {cid}: {'aprobada para contacto' if action == 'approve' else 'descartada'}.\n")
        return

    if action == "forget":
        cid = _need(args, "el id de la creadora")
        store.forget(cid)
        print(f"\n  {cid}: datos borrados. Queda solo su usuario marcado como baja, "
              "para no volver a añadirla.\n")
        return

    if action == "propose":
        cid = _need(args, "el id de la creadora")
        row = store.get(cid)
        if not row:
            sys.exit(f"  No existe {cid}")
        if row["status"] != "approved":
            sys.exit("  Antes de redactar, apruébala: harvey creators approve " + cid)
        config = _config()

        async def _write():
            from harvey.brain import Brain
            from harvey.creators.proposals import write_proposal
            from harvey.state import StateManager
            state = StateManager()
            await state.init_db()
            return await write_proposal(Brain(state, config.brain), row["creator"], config)
        language, subject, body, issues = asyncio.run(_write())
        pid = store.add_proposal(cid, language, subject, body, issues)
        print(f"\n  Propuesta {pid} ({language}) pendiente de tu revisión.\n")
        print(f"  Asunto: {subject}\n\n" + "\n".join("  " + line for line in body.splitlines()))
        if issues:
            print("\n  ✗ No se puede aprobar tal cual:")
            for i in issues:
                print(f"    - {i}")
        print()
        return

    if action == "proposals":
        for p in store.list_proposals(args.status):
            flag = " ✗" if p["issues"] else ""
            print(f"  [{p['id']}] creadora {p['creator_id']} · {p['language']} · "
                  f"{p['status']}{flag} · {p['subject']}")
        print()
        return

    if action == "show-proposal":
        p = store.get_proposal(_need(args, "el id de la propuesta"))
        if not p:
            sys.exit(f"  No existe {args.target}")
        print(f"\n  [{p['id']}] {p['status']} · {p['language']}\n  Asunto: {p['subject']}\n")
        print("\n".join("  " + line for line in p["body"].splitlines()))
        for i in p["issues"]:
            print(f"  ✗ {i}")
        print()
        return

    if action in ("approve-proposal", "reject-proposal"):
        pid = _need(args, "el id de la propuesta")
        p = store.get_proposal(pid)
        if not p:
            sys.exit(f"  No existe {pid}")
        if action == "approve-proposal" and p["issues"]:
            sys.exit("  Tiene problemas sin resolver; edítala o pide otra: "
                     + "; ".join(p["issues"]))
        store.set_proposal_status(pid, "approved" if action == "approve-proposal" else "rejected")
        print(f"\n  {pid}: {'aprobada' if action == 'approve-proposal' else 'rechazada'}. "
              f"{'Siguiente: harvey creators draft ' + pid if action == 'approve-proposal' else ''}\n")
        return

    if action == "draft":
        from harvey.creators.drafts import DraftRefused, create_gmail_draft, ready_draft
        pid = _need(args, "el id de la propuesta")
        config = _config()
        try:
            if args.export:
                print(json.dumps(ready_draft(store, pid, config), ensure_ascii=False, indent=2))
                return
            from harvey.config import load_env
            from harvey.integrations.gmail import GmailProvider
            provider = GmailProvider(config, load_env())
            if not provider.is_configured():
                sys.exit("  Gmail no está conectado aquí. Desde el iPhone usa --export y "
                         "pide a Claude que cree el borrador con el conector de Gmail.")
            ref = asyncio.run(create_gmail_draft(store, pid, config, provider))
        except DraftRefused as e:
            sys.exit(f"  No se crea el borrador: {e}")
        print(f"\n  Borrador creado en Gmail ({ref}). No se ha enviado nada: ábrelo en la "
              "app de Gmail, revísalo y envíalo tú.\n")
        return

    if action == "mark-drafted":
        # After Claude created the draft with the Gmail connector (from --export).
        from harvey.creators.drafts import DraftRefused, mark_drafted, ready_draft
        pid = _need(args, "el id de la propuesta")
        try:
            draft = ready_draft(store, pid, _config())
        except DraftRefused as e:
            sys.exit(f"  No se marca: {e}")
        mark_drafted(store, draft, args.ref or "connector")
        print(f"\n  {pid}: marcada como borrador en Gmail. Envíala tú cuando quieras.\n")
        return

    if action == "link":
        from harvey.creators.tracking import campaign_name, proposed_code, utm_link
        row = store.get(_need(args, "el id de la creadora"))
        if not row:
            sys.exit(f"  No existe {args.target}")
        config = _config()
        c, settings = row["creator"], config.creators
        campaign = campaign_name(c.country or "es", args.month or _this_month())
        print(f"\n  Enlace: {utm_link(settings.landing_base_url, c.platform, campaign, c.handle, args.path)}")
        if settings.offer.approved and settings.offer.community_discount_pct:
            code = proposed_code(c.display_name, c.handle,
                                 settings.offer.community_discount_pct, settings.code_prefix)
            print(f"  Código propuesto (créalo tú en Shopify): {code}")
        else:
            print("  Código: pendiente de que apruebes el descuento (creators.offer).")
        print()
        return

    if action == "report":
        _report(args, store)
        return

    if action == "queries":
        from harvey.creators.tracking import campaign_name, shopifyql_codes, shopifyql_sessions
        campaign = args.target or campaign_name("es", args.month or _this_month())
        print("\n  Consultas ShopifyQL de solo lectura (para el conector de Shopify):\n")
        print("  " + shopifyql_sessions(campaign) + "\n")
        print("  " + shopifyql_codes() + "\n")
        return

    if action == "purge":
        n = store.purge_stale_candidates()
        print(f"\n  {n} candidatas antiguas sin aprobar borradas.\n")


def _this_month() -> str:
    from datetime import date
    return date.today().strftime("%Y-%m")


def _report(args, store) -> None:
    """Results CSV (handle, sessions, orders, net_sales, gift_cost, fee) ->
    profitability table. The numbers come from the read-only Shopify queries."""
    from harvey.creators.tracking import Economics, profitability, report_markdown
    config = _config()
    econ = config.creators.economics
    offer = config.creators.offer
    if not econ.gross_margin_pct:
        sys.exit("  Falta creators.economics.gross_margin_pct (tu margen bruto, %).")
    results = []
    with open(_need(args, "el CSV de resultados"), newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            e = Economics(gross_margin_pct=econ.gross_margin_pct,
                          commission_pct=offer.commission_pct if offer.approved else 0.0,
                          gift_cost=float(row.get("gift_cost") or 0),
                          fee=float(row.get("fee") or 0))
            results.append(profitability(row["handle"].lstrip("@"), int(row.get("sessions") or 0),
                                         int(row.get("orders") or 0),
                                         float(row.get("net_sales") or 0), e))
    print("\n" + report_markdown(results, f"Resultados {args.month or ''}".strip()) + "\n")
