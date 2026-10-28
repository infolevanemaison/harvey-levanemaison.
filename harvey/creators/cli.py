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
           "show-proposal", "approve-proposal", "reject-proposal", "draft", "mark-drafted", "sent", "todo", "digest", "result",
           "followup", "reply", "inbox", "collab", "collab-set", "collabs", "link",
           "report", "queries", "purge", "backup", "restore", "check-backup", "add-proposal", "pipeline", "value")


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
    sub.add_argument("--text", default="", help="reply: her message (or --text-file)")
    sub.add_argument("--text-file", default="", help="reply: file with her message")
    sub.add_argument("--message-id", default="", help="reply: her Gmail message id, to answer in the thread")
    sub.add_argument("--terms", default="", help='collab: what was agreed, e.g. "1 vestido 45 EUR; 10%% comision"')
    sub.add_argument("--due", default="", help="collab: date the content is due, YYYY-MM-DD")
    sub.add_argument("fields", nargs="*", default=[], help="collab-set: field=value ...")
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

    if action in ("backup", "restore", "check-backup"):
        _cmd_backup(store, action, _need(args, "la carpeta del repositorio privado de datos"))
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

    if action == "pipeline":
        from harvey.creators.commerce import pipeline
        rows = pipeline(store.list_creators(), store.list_proposals())
        print(f"\n  Cartera de creadoras abiertas ({len(rows)}), de más a menos prioritaria:\n")
        for r in rows:
            canal = {"email": "email", "canal": "canal verificado"}.get(r["channel"], "sin canal")
            print(f"  [{r['id']}] {r['name'] or r['handle']} ({r['country']}) · {r['verdict']} · "
                  f"{canal} · prioridad {r['priority']}")
            print(f"      → {r['next']}")
        print()
        return

    if action == "value":
        # What a collaboration must sell to pay for itself. Nothing is offered.
        from harvey.creators.commerce import deal
        econ = _config().creators.economics
        fields = dict(f.split("=", 1) for f in (args.fields or []) if "=" in f)
        if args.target and "=" in args.target:
            k, v = args.target.split("=", 1)
            fields[k] = v
        try:
            fee = float(fields.get("fee", 0))
            aov = float(fields.get("aov", econ.avg_order_value_eur or 0))
            margin = float(fields.get("margin", econ.gross_margin_pct or 0))
            d = deal(fee, aov, margin, float(fields.get("commission", 0)), float(fields.get("gift", 0)))
        except ValueError:
            sys.exit("  Usa números: value fee=120 aov=55 margin=45 [commission=10] [gift=30]")
        if not aov or not margin:
            sys.exit("  Falta el ticket medio (aov=) o el margen (margin=): no los invento.")
        print("\n  Supuestos: " + "; ".join(d.assumptions))
        if d.unit_contribution is None:
            print("  Cada pedido pierde dinero con esa comisión: no es rentable.\n")
            return
        print(f"  Cada pedido deja {d.unit_contribution:.2f} EUR.")
        if d.break_even_orders is not None:
            print(f"  Pedidos necesarios para recuperar el coste: {d.break_even_orders}.")
        print("  Coste máximo (tarifa + producto) que se recupera con "
              + ", ".join(f"{n} pedidos: {v:.0f} EUR" for n, v in d.max_cost_for_orders.items()) + ".\n")
        return

    if action == "add-proposal":
        # A first message written outside Harvey's brain (by the daily routine
        # or by hand) goes through the same checks and waits for approval.
        from pathlib import Path
        from harvey.creators.proposals import check_proposal, proposal_language
        cid = _need(args, "el id de la creadora")
        row = store.get(cid)
        if not row:
            sys.exit(f"  No existe {cid}")
        if row["status"] in ("opted_out", "rejected"):
            sys.exit(f"  {cid} está en «{row['status']}»: no se le prepara ninguna propuesta.")
        if any(p["creator_id"] == cid and p["status"] in ("pending_review", "approved")
               for p in store.list_proposals()):
            sys.exit(f"  {cid} ya tiene una propuesta pendiente o aprobada.")
        if not args.text_file:
            sys.exit("  Falta --text-file: primera línea el asunto, después el cuerpo.")
        subject, _, body = Path(args.text_file).read_text(encoding="utf-8").strip().partition("\n")
        subject, body = subject.removeprefix("Asunto:").strip(), body.strip()
        language = proposal_language(row["creator"])
        issues = check_proposal(subject, body, language, _config().creators.offer)
        pid = store.add_proposal(cid, language, subject, body, issues)
        print(f"\n  Propuesta {pid} ({language}) guardada como pendiente de tu revisión. No se envía.")
        for i in issues:
            print(f"  ✗ {i}")
        print()
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

    if action == "sent":
        pid = _need(args, "el id de la propuesta")
        store.mark_sent(pid)
        print(f"\n  {pid}: enviada (por ti, desde Gmail). Harvey te avisará si toca seguimiento.\n")
        return

    if action == "todo":
        from harvey.creators.followups import due_actions
        actions = due_actions(store)
        if not actions:
            print("\n  Nada pendiente hoy.\n")
            return
        print(f"\n  {len(actions)} tareas pendientes (de más a menos urgente):\n")
        for a in actions:
            print(f"  [{a['priority']}] {a['who']}: {a['what']}\n      → {a['how']}")
        print()
        return

    if action == "result":
        # Numbers come from the read-only Shopify queries (harvey creators queries).
        cid = _need(args, "el id de la creadora")
        if not store.get(cid):
            sys.exit(f"  No existe {cid}")
        if not args.month:
            sys.exit("  Indica el periodo: --month AAAA-MM")
        values = {}
        for item in args.fields:
            key, _, value = item.partition("=")
            if key not in ("sessions", "orders", "net_sales", "gift_cost", "fee"):
                sys.exit(f"  Campo desconocido: {key}")
            values[key] = float(value.replace(",", ".")) if key in ("net_sales", "gift_cost", "fee") else int(value)
        store.record_result(cid, args.month, **values)
        print(f"\n  Resultados de {args.month} guardados para {cid}.\n")
        return

    if action == "digest":
        from harvey.creators.followups import digest
        print("\n" + digest(store) + "\n")
        return

    if action == "followup":
        cid = _need(args, "el id de la creadora")
        row = store.get(cid)
        if not row or row["status"] != "contacted":
            sys.exit("  Solo se prepara un recordatorio a quien recibió el primer mensaje y no respondió.")
        items = [p for p in store.list_proposals() if p["creator_id"] == cid]
        if any(p.get("kind") == "followup" for p in items):
            sys.exit("  Ya tiene un recordatorio: no se escribe más de una vez.")
        first = [p for p in items if p.get("kind", "first") == "first" and p["status"] == "sent"]
        if not first:
            sys.exit("  No consta ningún primer mensaje enviado (harvey creators sent <id>).")
        config = _config()

        async def _write():
            from harvey.creators.proposals import write_followup
            return await write_followup(await _brain(config), row["creator"], config,
                                        first[-1]["subject"])
        language, subject, body, issues = asyncio.run(_write())
        pid = store.add_proposal(cid, language, subject, body, issues, kind="followup")
        _show_new(pid, language, subject, body, issues)
        return

    if action == "reply":
        cid = _need(args, "el id de la creadora")
        text = args.text
        if args.text_file:
            with open(args.text_file, encoding="utf-8") as f:
                text = f.read()
        if not text.strip():
            sys.exit("  Falta su mensaje (--text o --text-file).")
        config = _config()

        async def _handle():
            from harvey.creators.followups import handle_reply
            return await handle_reply(store, cid, text, await _brain(config), config,
                                      message_id=args.message_id)
        result = asyncio.run(_handle())
        if result["outcome"] == "opt_out":
            print(f"\n  Baja: {result['why']} Sus datos se han borrado. No respondas salvo para "
                  "confirmarla si quieres.\n")
        elif result["outcome"] in ("escalate", "ignored"):
            print(f"\n  Sin respuesta automática: {result['why']}.\n")
        else:
            _show_new(result["proposal_id"], "", result["subject"], result["body"], result["issues"])
        return

    if action == "inbox":
        # A JSON export of Gmail messages (Claude reads them with the Gmail
        # connector). Personal data: keep the file out of the repository.
        path = _need(args, "el JSON con los mensajes")
        with open(path, encoding="utf-8") as f:
            messages = json.load(f)
        config = _config()

        async def _process():
            from harvey.creators.followups import process_inbox
            return await process_inbox(store, messages, await _brain(config), config)
        for r in asyncio.run(_process()):
            outcome = r["outcome"]
            label = {"opt_out": "BAJA aplicada", "escalate": "para ti (sin respuesta automática)",
                     "answer": f"respuesta propuesta {r.get('proposal_id', '')}",
                     "unknown_sender": "remitente desconocido: ignorado",
                     "already_handled": "ya procesado", "ignored": "ya era baja"}.get(outcome, outcome)
            print(f"  {r['from'] or '?'}: {label}")
        print()
        return

    if action == "collab":
        cid = _need(args, "el id de la creadora")
        if not args.terms:
            sys.exit('  Indica lo acordado: --terms "1 vestido (45 EUR); 10% comisión"')
        kid = store.add_collaboration(cid, {"acordado": args.terms}, content_due=args.due)
        print(f"\n  Colaboración {kid} registrada. Siguiente: harvey creators link {cid} --path ...\n")
        return

    if action == "collab-set":
        kid = _need(args, "el id de la colaboración")
        fields = {}
        for item in args.fields:
            if "=" not in item:
                sys.exit(f"  '{item}' no es campo=valor")
            key, value = item.split("=", 1)
            fields[key] = int(value) if key == "labelled_as_ad" else value
        store.update_collaboration(kid, **fields)
        print(f"\n  {kid} actualizada.\n")
        return

    if action == "collabs":
        for k in store.collaborations(args.status):
            row = store.get(k["creator_id"])
            label = {None: "sin comprobar", 0: "NO", 1: "sí"}.get(k["labelled_as_ad"], "?")
            print(f"  [{k['id']}] @{row['handle'] if row else k['creator_id']} · {k['status']} · "
                  f"{k['terms'].get('acordado', '')} · publicidad etiquetada: {label}")
        print()
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


async def _brain(config):
    from harvey.brain import Brain
    from harvey.state import StateManager
    state = StateManager()
    await state.init_db()
    return Brain(state, config.brain)


def _show_new(pid, language, subject, body, issues) -> None:
    print(f"\n  Propuesta {pid} {('(' + language + ') ') if language else ''}pendiente de tu revisión.\n")
    print(f"  Asunto: {subject}\n\n" + "\n".join("  " + line for line in body.splitlines()))
    if issues:
        print("\n  ✗ No se puede aprobar tal cual:")
        for i in issues:
            print(f"    - {i}")
    print()


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


def _cmd_backup(store, action: str, folder: str) -> None:
    """Save the whole store to, or load it from, the private data repo's folder."""
    from pathlib import Path
    from harvey.paths import PROJECT_ROOT
    from harvey.creators import sync
    target = Path(folder).resolve()
    if target == PROJECT_ROOT.resolve() or PROJECT_ROOT.resolve() in target.parents:
        raise SystemExit("  Esa carpeta está dentro del repositorio público de Harvey. "
                         "Usa el clon del repositorio privado de datos.")
    try:
        if action == "backup":
            manifest = sync.dump(store, target)
            counts = ", ".join(f"{t} {m['filas']}" for t, m in manifest["tablas"].items())
            print(f"\n  Copia escrita en {target}: {counts}.")
            print("  Falta: git add, commit y push en el repositorio privado.\n")
        elif action == "restore":
            counts = sync.restore(store, target)
            print(f"\n  Datos recuperados de {target}: "
                  + ", ".join(f"{t} {n}" for t, n in counts.items()) + ".\n")
        else:
            same = sync.matches(store, target)
            for table, ok in same.items():
                print(f"  {'OK ' if ok else 'DIF'}  {table}")
            if not all(same.values()):
                raise SystemExit("  La base local y la copia no coinciden.")
            print("  La base local y la copia coinciden.\n")
    except sync.BackupError as e:
        raise SystemExit(f"  Copia no válida: {e}") from None
