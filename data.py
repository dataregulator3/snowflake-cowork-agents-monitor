"""Data loading and filter helpers shared by all pages."""

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import config

TIME_RANGES = {"2 weeks": 14, "1 month": 30, "3 months": 90, "6 months": 180, "1 year": 365}
ALL_AGENTS = "All agents"
CURRENCY_SYMBOLS = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3"}

conn = st.connection("snowflake")

# CoWork (Snowflake Intelligence UI) and direct Cortex Agent API calls; REQUEST_IDs don't overlap.
USAGE_SOURCE = """(
    SELECT 'CoWork' AS CHANNEL, START_TIME, END_TIME, USER_NAME, REQUEST_ID, THREAD_ID, TOKEN_CREDITS, TOKENS,
           AGENT_DATABASE_NAME, AGENT_SCHEMA_NAME, AGENT_NAME, METADATA, CREDITS_GRANULAR, TOKENS_GRANULAR
    FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_COWORK_USAGE_HISTORY
    UNION ALL
    SELECT 'API', START_TIME, END_TIME, USER_NAME, REQUEST_ID, THREAD_ID, TOKEN_CREDITS, TOKENS,
           AGENT_DATABASE_NAME, AGENT_SCHEMA_NAME, AGENT_NAME, METADATA, CREDITS_GRANULAR, TOKENS_GRANULAR
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
)"""


def display_name(agent: str) -> str:
    return config.AGENT_DISPLAY_NAMES.get(agent, agent)


def _location_filter() -> tuple[str, list]:
    """SQL condition and bind parameters for config.AGENT_LOCATIONS."""
    clauses, params = [], []
    for values in config.AGENT_LOCATIONS:
        parts = []
        for column, value in zip(("AGENT_DATABASE_NAME", "AGENT_SCHEMA_NAME", "AGENT_NAME"), values):
            if value:
                params.append(value)
                parts.append(f"{column} = :{len(params)}")
        clauses.append("(" + (" AND ".join(parts) or "TRUE") + ")")
    return ("(" + " OR ".join(clauses) + ")" if clauses else "TRUE"), params


# ---------------------------------------------------------------------------
# Data loading. The full history is small (one row per request), so it is
# loaded once and filtered in pandas. Refresh clears the cache.
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300, show_spinner="Loading agent usage...")
def load_requests() -> pd.DataFrame:
    location, params = _location_filter()
    df = conn.query(
        f"""
        SELECT
            CHANNEL,
            DATE(START_TIME) AS usage_date,
            START_TIME,
            USER_NAME,
            REQUEST_ID,
            COALESCE(TO_VARCHAR(THREAD_ID), REQUEST_ID) AS conversation_id,
            AGENT_NAME,
            TOKEN_CREDITS,
            TOKENS,
            DATEDIFF('millisecond', START_TIME, END_TIME) / 1000 AS duration_s,
            METADATA:agent_version_name::STRING AS agent_version,
            METADATA:agent_version_is_default::BOOLEAN AS version_is_default,
            METADATA:sql_query_credits::FLOAT AS sql_credits,
            ARRAY_TO_STRING(METADATA:sql_query_warehouses::ARRAY, ',') AS sql_warehouses
        FROM {USAGE_SOURCE}
        WHERE AGENT_NAME IS NOT NULL AND {location}
        """,
        params=params or None,
        ttl=300,
    )
    df.columns = df.columns.str.lower()
    df["usage_date"] = pd.to_datetime(df["usage_date"]).dt.date
    df["token_credits"] = df["token_credits"].astype(float)
    df["tokens"] = df["tokens"].fillna(0).astype(int)
    df["duration_s"] = df["duration_s"].astype(float)
    df["sql_credits"] = df["sql_credits"].astype(float).fillna(0)
    df["sql_warehouses"] = df["sql_warehouses"].fillna("")
    df["agent_version"] = df["agent_version"].fillna("unknown")
    return df


@st.cache_data(ttl=300, show_spinner="Loading model usage...")
def load_granular() -> pd.DataFrame:
    """Credits and tokens per request, model and kind (input, output, cache read/write)."""
    location, params = _location_filter()
    df = conn.query(
        f"""
        WITH src AS (
            SELECT REQUEST_ID, CREDITS_GRANULAR, TOKENS_GRANULAR FROM {USAGE_SOURCE}
            WHERE AGENT_NAME IS NOT NULL AND {location}
        ),
        credits AS (
            SELECT s.REQUEST_ID, m.key AS model, k.key AS kind, k.value::FLOAT AS credits
            FROM src s, LATERAL FLATTEN(s.CREDITS_GRANULAR) g, LATERAL FLATTEN(g.value) r,
                 LATERAL FLATTEN(r.value) svc, LATERAL FLATTEN(svc.value) m, LATERAL FLATTEN(m.value) k
            WHERE svc.key <> 'start_time'
        ),
        tokens AS (
            SELECT s.REQUEST_ID, m.key AS model, k.key AS kind, k.value::FLOAT AS tokens
            FROM src s, LATERAL FLATTEN(s.TOKENS_GRANULAR) g, LATERAL FLATTEN(g.value) r,
                 LATERAL FLATTEN(r.value) svc, LATERAL FLATTEN(svc.value) m, LATERAL FLATTEN(m.value) k
            WHERE svc.key <> 'start_time'
        )
        SELECT REQUEST_ID, model, kind, SUM(credits) AS credits, SUM(tokens) AS tokens
        FROM credits FULL JOIN tokens USING (REQUEST_ID, model, kind)
        GROUP BY REQUEST_ID, model, kind
        """,
        params=params or None,
        ttl=300,
    )
    df.columns = df.columns.str.lower()
    df["credits"] = df["credits"].astype(float).fillna(0)
    df["tokens"] = df["tokens"].astype(float).fillna(0)
    return df


@st.cache_data(ttl=300, show_spinner="Loading warehouse metering...")
def load_warehouse_daily(warehouses: tuple[str, ...]) -> pd.DataFrame:
    if not warehouses:
        return pd.DataFrame(columns=["usage_date", "warehouse_name", "compute_credits", "cloud_credits"])
    placeholders = ", ".join(f":{i}" for i in range(1, len(warehouses) + 1))
    df = conn.query(
        f"""
        SELECT
            DATE(START_TIME) AS usage_date,
            WAREHOUSE_NAME,
            SUM(CREDITS_USED_COMPUTE) AS compute_credits,
            SUM(CREDITS_USED_CLOUD_SERVICES) AS cloud_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE WAREHOUSE_NAME IN ({placeholders})
          AND START_TIME >= DATEADD(day, -370, CURRENT_DATE())
        GROUP BY DATE(START_TIME), WAREHOUSE_NAME
        """,
        params=list(warehouses),
        ttl=300,
    )
    df.columns = df.columns.str.lower()
    df["usage_date"] = pd.to_datetime(df["usage_date"]).dt.date
    df["compute_credits"] = df["compute_credits"].astype(float)
    df["cloud_credits"] = df["cloud_credits"].astype(float)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_rates() -> dict:
    """Current effective price per credit from the rate sheet, or the configured fallback."""
    fallback = {
        "ai": config.FALLBACK_AI_CREDIT_PRICE,
        "compute": config.FALLBACK_COMPUTE_CREDIT_PRICE,
        "currency": config.FALLBACK_CURRENCY,
        "source": "config",
    }
    try:
        df = conn.query(
            """
            SELECT SERVICE_TYPE, EFFECTIVE_RATE, CURRENCY
            FROM SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY
            WHERE SERVICE_TYPE IN ('SNOWFLAKE_COWORK', 'WAREHOUSE_METERING')
              AND ACCOUNT_LOCATOR = CURRENT_ACCOUNT()
              AND DATE >= DATEADD(day, -60, CURRENT_DATE())
            QUALIFY ROW_NUMBER() OVER (PARTITION BY SERVICE_TYPE ORDER BY DATE DESC) = 1
            """,
            ttl=3600,
        )
    except Exception:
        return fallback
    rows = {r.SERVICE_TYPE: r for r in df.itertuples()}
    if not {"SNOWFLAKE_COWORK", "WAREHOUSE_METERING"} <= rows.keys():
        return fallback
    return {
        "ai": float(rows["SNOWFLAKE_COWORK"].EFFECTIVE_RATE),
        "compute": float(rows["WAREHOUSE_METERING"].EFFECTIVE_RATE),
        "currency": rows["SNOWFLAKE_COWORK"].CURRENCY,
        "source": "rate sheet",
    }


@st.cache_data(ttl=3600, show_spinner=False)
def load_auto_suspend(warehouse: str) -> int | None:
    """AUTO_SUSPEND in seconds, or None if the warehouse is not visible to the app role."""
    try:
        # conn.query() can't fetch SHOW results and SHOW doesn't take binds; name comes from config
        cur = conn.cursor()
        cur.execute("SHOW WAREHOUSES LIKE '{}'".format(warehouse.replace("'", "''")))
        row = cur.fetchone()
        if row is None:
            return None
        columns = [c[0].lower() for c in cur.description]
        return int(row[columns.index("auto_suspend")])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Filters (widgets live in the entry script, values are read here)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Filters:
    start: date
    end: date
    days: int
    agent: str | None
    show_costs: bool


def filters() -> Filters:
    days = TIME_RANGES[st.session_state.get("range") or "2 weeks"]
    end = date.today()
    agent = st.session_state.get("agent")
    return Filters(
        start=end - timedelta(days=days),
        end=end,
        days=days,
        agent=None if agent in (None, ALL_AGENTS) else agent,
        show_costs=st.session_state.get("show_costs", True),
    )


def filter_requests(df: pd.DataFrame, f: Filters, by_agent: bool = True) -> pd.DataFrame:
    mask = (df["usage_date"] >= f.start) & (df["usage_date"] <= f.end)
    if by_agent and f.agent:
        mask &= df["agent_name"] == f.agent
    return df[mask]


# ---------------------------------------------------------------------------
# Periods: days for short ranges, ISO weeks from 3 months, months from 6 months
# ---------------------------------------------------------------------------


def period_of(dates: pd.Series, days: int) -> pd.Series:
    fmt = "%Y-%m" if days >= 180 else "%G-W%V" if days >= 90 else "%Y-%m-%d"
    return pd.to_datetime(dates).dt.strftime(fmt)


def periods(f: Filters) -> list[str]:
    return list(dict.fromkeys(period_of(pd.Series(pd.date_range(f.start, f.end, freq="D")), f.days)))


def per_period(df: pd.DataFrame, value_col: str, group_col: str, f: Filters, agg="sum") -> pd.DataFrame:
    """Aggregate value_col per period and group. Sums are filled with 0 for empty periods."""
    grouped = (
        df.assign(period=period_of(df["usage_date"], f.days))
        .groupby(["period", group_col])[value_col]
        .agg(agg)
        .rename("value")
        .reset_index()
    )
    groups = grouped[group_col].unique().tolist()
    grid = pd.MultiIndex.from_product([periods(f), groups], names=["period", group_col]).to_frame(index=False)
    out = grid.merge(grouped, on=["period", group_col], how="left")
    if agg in ("sum", "count", "nunique"):
        out["value"] = out["value"].fillna(0)
    return out


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _symbol(currency: str) -> str:
    return CURRENCY_SYMBOLS.get(currency, f"{currency} ")


def money(credits: float, kind: str) -> str:
    """Format credits as cost. kind is 'ai' or 'compute'."""
    rates = load_rates()
    amount = credits * rates[kind]
    text = f"{_symbol(rates['currency'])}{amount:,.2f}"
    if config.SECONDARY_CURRENCY:
        code, fx = config.SECONDARY_CURRENCY
        text += f" / {_symbol(code)}{amount * fx:,.2f}"
    return text


def header_caption(f: Filters) -> str:
    text = f"{f.start:%Y-%m-%d} to {f.end:%Y-%m-%d}"
    if f.show_costs:
        rates = load_rates()
        sym = _symbol(rates["currency"])
        text += (
            f" | AI credit: {sym}{rates['ai']:.2f}, compute credit: {sym}{rates['compute']:.2f}"
            f" ({rates['source']})"
        )
        if config.SECONDARY_CURRENCY:
            code, fx = config.SECONDARY_CURRENCY
            text += f" | {rates['currency']}/{code}: {fx}"
    return text


def page_title(name: str, icon: str, f: Filters) -> None:
    st.title(f"{icon} {name}" + (f" \u2014 {display_name(f.agent)}" if f.agent else ""))
    st.caption(header_caption(f))
