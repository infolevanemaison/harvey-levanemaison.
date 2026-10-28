"""The read-only queries the watch runs. Each passes guard.check_query."""

from harvey.shopaudit import PRODUCTS_QUERY

ORDERS_QUERY = """query($first: Int!, $after: String, $q: String) {
  orders(first: $first, after: $after, query: $q, sortKey: CREATED_AT, reverse: true) {
    nodes {
      name createdAt cancelledAt closed test sourceName
      displayFinancialStatus displayFulfillmentStatus
      totalPriceSet { shopMoney { amount } }
      totalRefundedSet { shopMoney { amount } }
      transactions(first: 5) { kind status gateway }
      shippingAddress { countryCodeV2 }
      fulfillments(first: 5) {
        createdAt updatedAt status displayStatus estimatedDeliveryAt inTransitAt deliveredAt
        trackingInfo(first: 3) { company number }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}"""

THEME_QUERY = "{ themes(first: 1, roles: [MAIN]) { nodes { id name role updatedAt } } }"

# Meta Marketing API, GET only. Fields of /act_<id>/campaigns and /insights.
META_CAMPAIGN_FIELDS = "id,name,effective_status,daily_budget,lifetime_budget,stop_time"
META_INSIGHT_FIELDS = "campaign_id,campaign_name,spend,actions"

SHOPIFY_QUERIES = {"orders": ORDERS_QUERY, "products": PRODUCTS_QUERY, "theme": THEME_QUERY}
