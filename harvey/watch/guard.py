"""What a watch query may ask for.

Only plain queries pass: no mutation, no subscription, no introspection.
Customer data stays out: a query may not name customers, emails, phones,
names or street addresses. The shipping country is allowed, nothing else of
the address.
"""

import re

FORBIDDEN_OPERATIONS = ("mutation", "subscription", "__schema", "__type")
# Fields that carry a person's data. ``countryCodeV2`` is the one address
# field the watch needs, so ``address`` alone is not banned, only its parts.
FORBIDDEN_FIELDS = (
    "customer", "customers", "email", "phone", "firstName", "lastName", "displayName",
    "address1", "address2", "zip", "city", "province", "company", "note", "clientIp",
    "browserIp", "billingAddress", "customAttributes", "contactEmail",
)
ALLOWED_ADDRESS_FIELDS = ("countryCodeV2", "countryCode")


class UnsafeQuery(ValueError):
    pass


def _words(query: str) -> set[str]:
    # Strings ("status:active") are not fields: drop them before looking.
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", re.sub(r'"[^"]*"', " ", query)))


def check_query(query: str) -> str:
    """Return the query if it is a safe read; raise UnsafeQuery otherwise."""
    stripped = re.sub(r"#[^\n]*", " ", query or "").strip()
    if not stripped:
        raise UnsafeQuery("consulta vacía")
    words = _words(stripped)
    lowered = {w.lower() for w in words}
    for op in FORBIDDEN_OPERATIONS:
        if op.lower() in lowered:
            raise UnsafeQuery(f"operación no permitida: {op}")
    if not stripped.startswith(("{", "query")):
        raise UnsafeQuery("solo se permiten consultas de lectura")
    bad = sorted(f for f in FORBIDDEN_FIELDS if f in words)
    # trackingInfo.company is the carrier, not a person: allow it there only.
    if ("company" in bad
            and re.search(r"trackingInfo[^{}]*\{[^{}]*\bcompany\b", stripped)
            and not re.search(r"(?:shippingAddress|Address)\s*\{[^{}]*\bcompany\b", stripped)):
        bad.remove("company")
    if bad:
        raise UnsafeQuery("pide datos personales: " + ", ".join(bad))
    return query
