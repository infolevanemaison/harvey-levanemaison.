"""Store watch: read-only checks on orders, deliveries, catalog and ads.

Everything here reads. ``guard`` refuses any GraphQL that is not a plain
query or that asks for a customer's personal data, ``fetch`` only sends GET
requests to Meta and read queries to Shopify, ``checks`` turns snapshots
into alerts, and ``alerts`` keeps state between runs so the owner hears about
a problem once, when it starts, and again when it is solved.
"""
