"""Read-only fetchers for the watch, with a hard cap on requests.

Shopify: a Dev Dashboard app installed on the store with read scopes only
(read_orders, read_products, read_inventory, read_themes). Each run trades
its client id and secret for a 24-hour token (client credentials grant),
keeps it in memory, and refuses to go on if the token carries any scope that
is not a read scope, so a mistake in the app setup cannot turn into a write.
Every query also goes through ``guard.check_query``. Meta: GET only, with an
``ads_read`` token. Secrets come from the environment and never appear in
errors, reports or files.
"""

import os
import time

import httpx

from harvey.watch.guard import check_query
from harvey.watch.queries import (
    META_CAMPAIGN_FIELDS,
    META_INSIGHT_FIELDS,
    SHOPIFY_QUERIES,
    VARIANTS_FILTER,
)

SHOPIFY_API_VERSION = "2026-10"
META_API_VERSION = "v24.0"


class Budget:
    """At most ``limit`` requests per run, whatever happens."""

    def __init__(self, limit: int = 40):
        self.limit, self.used = limit, 0

    def spend(self) -> None:
        if self.used >= self.limit:
            raise RuntimeError(f"límite de {self.limit} peticiones por ejecución alcanzado")
        self.used += 1


def _clean(message: str, *secrets: str) -> str:
    for s in secrets:
        if s:
            message = message.replace(s, "***")
    return message


READ_SCOPES_ALLOWED = ("read_",)


def shopify_token(shop: str, client_id: str, client_secret: str, budget: Budget,
                  client: httpx.Client | None = None) -> str:
    """Client credentials grant. Returns the token only if every scope is a read scope."""
    if not shop.endswith(".myshopify.com"):
        raise ValueError("SHOPIFY_SHOP debe ser <tienda>.myshopify.com")
    budget.spend()
    client = client or httpx.Client(timeout=20)
    try:
        r = client.post(f"https://{shop}/admin/oauth/access_token",
                        data={"client_id": client_id, "client_secret": client_secret,
                              "grant_type": "client_credentials"})
        r.raise_for_status()
        body = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise RuntimeError(_clean(f"Shopify (token): {e}", client_id, client_secret)) from None
    token = body.get("access_token") or ""
    scopes = [x.strip() for x in str(body.get("scope") or "").split(",") if x.strip()]
    if not token:
        raise RuntimeError("Shopify (token): respuesta sin token")
    unsafe = [x for x in scopes if not x.startswith(READ_SCOPES_ALLOWED)]
    if unsafe or not scopes:
        raise RuntimeError("PARADA: la app de Shopify tiene permisos que no son de lectura: "
                           + (", ".join(unsafe) or "ninguno declarado")
                           + ". Quítalos en el Dev Dashboard antes de seguir.")
    return token


def summarise_errors(errors) -> str:
    """Distinct messages only: one denied field must not fill a report with 50 copies."""
    if not isinstance(errors, list):
        return str(errors)[:200]
    seen = []
    for e in errors:
        msg = (e.get("message") if isinstance(e, dict) else str(e)) or "error"
        code = (e.get("extensions") or {}).get("code", "") if isinstance(e, dict) else ""
        text = f"{msg} ({code})" if code else msg
        if text not in seen:
            seen.append(text[:200])
    more = f" y {len(seen) - 3} más" if len(seen) > 3 else ""
    return "; ".join(seen[:3]) + more


class ShopifyReader:
    def __init__(self, shop: str, token: str, budget: Budget, client: httpx.Client | None = None):
        if not shop.endswith(".myshopify.com"):
            raise ValueError("SHOPIFY_SHOP debe ser <tienda>.myshopify.com")
        self.url = f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
        self.token, self.budget = token, budget
        self.client = client or httpx.Client(timeout=20)
        self.sleep = time.sleep

    def query(self, query: str, variables: dict | None = None, retries: int = 3) -> dict:
        check_query(query)
        for attempt in range(retries + 1):
            self.budget.spend()
            try:
                r = self.client.post(self.url, json={"query": query, "variables": variables or {}},
                                     headers={"X-Shopify-Access-Token": self.token})
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise RuntimeError(_clean(f"Shopify: {e}", self.token)) from None
            body = r.json()
            throttled = any((e.get("extensions") or {}).get("code") == "THROTTLED"
                            for e in body.get("errors") or [] if isinstance(e, dict))
            if not throttled or attempt == retries:
                break
            # Shopify refills its query budget every second: wait, then try again.
            self.sleep(2 * (attempt + 1))
        if body.get("errors"):
            raise RuntimeError(_clean(f"Shopify: {summarise_errors(body['errors'])}", self.token))
        return body.get("data") or {}

    def nodes(self, name: str, root: str, variables: dict, max_pages: int = 5) -> list[dict]:
        out, after = [], None
        for _ in range(max_pages):
            data = self.query(SHOPIFY_QUERIES[name], {**variables, "after": after})[root]
            out += data.get("nodes") or []
            info = data.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                break
            after = info.get("endCursor")
        return out


class MetaReader:
    def __init__(self, account_id: str, token: str, budget: Budget, client: httpx.Client | None = None):
        account_id = account_id.removeprefix("act_")
        if not account_id.isdigit():
            raise ValueError("META_AD_ACCOUNT debe ser el número de la cuenta")
        self.base = f"https://graph.facebook.com/{META_API_VERSION}/act_{account_id}"
        self.token, self.budget = token, budget
        self.client = client or httpx.Client(timeout=20)

    def _get(self, path: str, params: dict) -> list[dict]:
        self.budget.spend()
        try:
            r = self.client.get(f"{self.base}/{path}", params={**params, "access_token": self.token})
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(_clean(f"Meta: {e}", self.token)) from None
        return r.json().get("data") or []

    def campaigns(self) -> list[dict]:
        return self._get("campaigns", {"fields": META_CAMPAIGN_FIELDS, "limit": 100})

    def insights_today(self) -> list[dict]:
        return self._get("insights", {"fields": META_INSIGHT_FIELDS, "level": "campaign",
                                      "date_preset": "today", "limit": 100})


def snapshot_from_env(env=os.environ, budget: Budget | None = None,
                      order_days: int = 60) -> tuple[dict, list[str]]:
    """Fetch whatever the environment has tokens for. Returns (snapshot, errors)."""
    from datetime import UTC, datetime, timedelta
    budget = budget or Budget()
    snap, errors = {}, []
    shop = env.get("SHOPIFY_SHOP", "")
    cid, secret = env.get("SHOPIFY_CLIENT_ID", ""), env.get("SHOPIFY_CLIENT_SECRET", "")
    token = ""
    if shop and cid and secret:
        try:
            token = shopify_token(shop, cid, secret, budget)
            reader = ShopifyReader(shop, token, budget)
        except Exception as e:  # noqa: BLE001 - a failed source is reported, not fatal
            errors.append(_clean(str(e), token, cid, secret))
            reader = None
        since = (datetime.now(UTC) - timedelta(days=order_days)).date().isoformat()
        # Each source on its own: one that fails must not hide the others.
        sources = {
            "orders": lambda: reader.nodes("orders", "orders", {"first": 50, "q": f"created_at:>={since}"}),
            "products": lambda: reader.nodes("products", "products", {"first": 50}),
            "theme": lambda: (reader.query(SHOPIFY_QUERIES["theme"])["themes"]["nodes"] or [{}])[0],
            "variants": lambda: reader.nodes("variants", "productVariants",
                                             {"first": 250, "q": VARIANTS_FILTER}, max_pages=20),
        }
        for key, read in sources.items() if reader else ():
            try:
                snap[key] = read()
            except Exception as e:  # noqa: BLE001
                errors.append(_clean(f"{key}: {e}", token, cid, secret))
    account, mtoken = env.get("META_AD_ACCOUNT", ""), env.get("META_READ_TOKEN", "")
    if account and mtoken:
        try:
            reader = MetaReader(account, mtoken, budget)
            snap["campaigns"] = reader.campaigns()
            snap["insights"] = reader.insights_today()
        except Exception as e:  # noqa: BLE001
            errors.append(_clean(str(e), mtoken))
    return snap, errors
