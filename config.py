"""Account-specific settings for the CoWork Agents Monitor. Redeploy after changing this file."""

# Agents to include. Each entry is (database, schema, agent_name); None matches anything.
# Examples:
#   [("MY_DB", "AGENTS", None)]                          all agents in MY_DB.AGENTS
#   [("MY_DB", None, None), (None, None, "SALES_BOT")]   all agents in MY_DB plus SALES_BOT anywhere
# An empty list includes every agent in the account.
AGENT_LOCATIONS: list[tuple[str | None, str | None, str | None]] = []

# Warehouses your agents' tools run on. Empty hides the warehouse utilization section.
AGENT_WAREHOUSES: list[str] = []

# Prices are read from SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY.
# These values are used if that view is not accessible to the app's owner role.
FALLBACK_AI_CREDIT_PRICE: float = 2.00
FALLBACK_COMPUTE_CREDIT_PRICE: float = 2.00
FALLBACK_CURRENCY: str = "USD"

# Optional second currency shown next to costs: (currency code, conversion rate), e.g. ("EUR", 0.92).
SECONDARY_CURRENCY: tuple[str, float] | None = None

# Optional pretty names for agents, keyed by the technical AGENT_NAME, e.g. {"SALES_BOT": "Sales Assistant"}.
AGENT_DISPLAY_NAMES: dict[str, str] = {}
