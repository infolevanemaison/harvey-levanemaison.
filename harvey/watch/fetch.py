"""Read-only fetchers for the watch, with a hard cap on requests.

Shopify: POST to the Admin GraphQL endpoint, but every query goes through
``guard.check_query`` first, and the token is meant to be a custom app's
read-only token (read_orders, read_products, read_inventory, read_themes),
so Shopify itself refuses any write. Meta: GET only, with an ``ads_read``
token. Tokens come from the environment and never appear in errors or logs.
"""

import os

import httpx

from harvey.watch.guard import check_query
from harvey.watch.queries import (
    META_CAMPAIGN_FIELDS,
    META_INSIGHT_FIELDS,
    SHOPIFY_QUERIES,
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


class ShopifyReader:
    def __init__(self, shop: str, token: str, budget: Budget, client: httpx.Client | None = None):
        if not shop.endswith(".myshopify.com"):
            raise ValueError("SHOPIFY_SHOP debe ser <tienda>.myshopify.com")
        self.url = f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
        self.token, self.budget = token, budget
        self.client = client or httpx.Client(timeout=20)

    def query(self, query: str, variables: dict | None = None) -> dict:
        check_query(query)
        self.budget.spend()
        try:
            r = self.client.post(self.url, json={"query": query, "variables": variables or {}},
                                 headers={"X-Shopify-Access-Token": self.token})
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(_clean(f"Shopify: {e}", self.token)) from None
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(_clean(f"Shopify: {body['errors']}", self.token))
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
    shop, token = env.get("SHOPIFY_SHOP", ""), env.get("SHOPIFY_READ_TOKEN", "")
    if shop and token:
        try:
            reader = ShopifyReader(shop, token, budget)
            since = (datetime.now(UTC) - timedelta(days=order_days)).date().isoformat()
            snap["orders"] = reader.nodes("orders", "orders", {"first": 50, "q": f"created_at:>={since}"})
            snap["products"] = reader.nodes("products", "products", {"first": 50})
            themes = reader.query(SHOPIFY_QUERIES["theme"])["themes"]["nodes"]
            snap["theme"] = themes[0] if themes else {}
        except Exception as e:  # noqa: BLE001 - a failed source is reported, not fatal
            errors.append(_clean(str(e), token))
    account, mtoken = env.get("META_AD_ACCOUNT", ""), env.get("META_READ_TOKEN", "")
    if account and mtoken:
        try:
            reader = MetaReader(account, mtoken, budget)
            snap["campaigns"] = reader.campaigns()
            snap["insights"] = reader.insights_today()
        except Exception as e:  # noqa: BLE001
            errors.append(_clean(str(e), mtoken))
    return snap, errors
