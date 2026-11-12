import altair as alt
import pandas as pd
import streamlit as st

import charts
import config
import data

f = data.filters()
data.page_title("Cost & compute", ":material/payments:", f)

all_req = data.filter_requests(data.load_requests(), f, by_agent=False)
req = data.filter_requests(all_req, f)
if req.empty:
    st.warning("No agent usage in this period.")
    st.stop()

req = req.assign(agent_name=req["agent_name"].map(data.display_name))
granular = data.load_granular().merge(req[["request_id", "agent_name", "usage_date"]], on="request_id")

# ---------------------------------------------------------------------------
st.subheader("AI credits by model")
st.caption("LLM credits per model, from CREDITS_GRANULAR.")
charts.stacked_bars(data.per_period(granular, "credits", "model", f), "model", "AI credits", "Model")

by_model = granular.pivot_table(index="agent_name", columns="model", values="credits", aggfunc="sum", fill_value=0)
st.dataframe(
    by_model.round(2),
    column_config={"agent_name": "Agent"},
)

# ---------------------------------------------------------------------------
st.subheader("Prompt caching")
st.caption(
    "Cache hit rate = cached input tokens / all input tokens. Cache writes are billed at a premium, "
    "so a high write share with a low hit rate means prompts are rarely reused."
)
kinds = granular.pivot_table(
    index="agent_name", columns="kind", values=["tokens", "credits"], aggfunc="sum", fill_value=0
)
cache = pd.DataFrame(index=kinds.index)
input_tokens = sum(kinds.get(("tokens", k), 0) for k in ("input", "cache_read_input", "cache_write_input"))
cache["hit_rate"] = kinds.get(("tokens", "cache_read_input"), 0) / input_tokens.where(input_tokens > 0)
total_credits = kinds["credits"].sum(axis=1)
for kind in ("cache_write_input", "cache_read_input", "output", "input"):
    cache[f"share_{kind}"] = kinds.get(("credits", kind), 0) / total_credits.where(total_credits > 0)
cache = cache.reset_index().sort_values("share_cache_write_input", ascending=False)

pct = st.column_config.ProgressColumn
st.dataframe(
    cache,
    hide_index=True,
    column_config={
        "agent_name": "Agent",
        "hit_rate": pct("Cache hit rate", format="percent", min_value=0, max_value=1),
        "share_cache_write_input": pct("Credits: cache write", format="percent", min_value=0, max_value=1),
        "share_cache_read_input": pct("Credits: cache read", format="percent", min_value=0, max_value=1),
        "share_output": pct("Credits: output", format="percent", min_value=0, max_value=1),
        "share_input": pct("Credits: input", format="percent", min_value=0, max_value=1),
    },
)

# ---------------------------------------------------------------------------
st.subheader("SQL compute by agent")
st.caption("Warehouse credits of the SQL queries agents ran (METADATA:sql_query_credits).")
sql_credits = req["sql_credits"].sum()
with st.container(horizontal=True):
    st.metric("SQL credits", f"{sql_credits:,.3f}", border=True)
    if f.show_costs:
        st.metric("Est. SQL cost", data.money(sql_credits, "compute"), border=True)
    st.metric("Requests with SQL", f"{(req['sql_credits'] > 0).sum():,}", border=True)
charts.stacked_bars(data.per_period(req, "sql_credits", "agent_name", f), "agent_name", "SQL credits", "Agent", fmt=",.4f")

# ---------------------------------------------------------------------------
warehouses = tuple(config.AGENT_WAREHOUSES)
if warehouses:
    st.subheader("Warehouse utilization")
    st.caption(
        "Metered = what the warehouse billed (WAREHOUSE_METERING_HISTORY), including idle time until auto-suspend "
        "and any non-agent workload. Used by agents = SQL credits of agent requests on that warehouse. "
        "Shows all agents, independent of the agent filter."
    )
    metered = data.load_warehouse_daily(warehouses)
    metered = metered[(metered["usage_date"] >= f.start) & (metered["usage_date"] <= f.end)]

    for wh in warehouses:
        wh_metered = metered[metered["warehouse_name"] == wh]
        wh_used = all_req[all_req["sql_warehouses"].str.split(",").map(lambda w: wh in w)]
        paid, used = wh_metered["compute_credits"].sum(), wh_used["sql_credits"].sum()
        suspend = data.load_auto_suspend(wh)

        with st.container(horizontal=True):
            st.metric(f"{wh}: metered credits", f"{paid:,.2f}", border=True)
            st.metric("Used by agents", f"{used:,.3f}", border=True)
            st.metric("Utilization", f"{used / paid:.0%}" if paid else "n/a", border=True)
            if f.show_costs:
                st.metric("Est. metered cost", data.money(paid, "compute"), border=True)
            st.metric("Auto-suspend", f"{suspend} s" if suspend is not None else "n/a", border=True)

        series = pd.concat(
            [
                data.per_period(wh_metered.assign(series="Metered"), "compute_credits", "series", f),
                data.per_period(wh_used.assign(series="Used by agents"), "sql_credits", "series", f),
            ]
        )
        chart = (
            alt.Chart(series)
            .mark_bar()
            .encode(
                x=alt.X("period:N", title=None, sort=None),
                xOffset="series:N",
                y=alt.Y("value:Q", title="Credits"),
                color=alt.Color("series:N", title=None),
                tooltip=["period:N", "series:N", alt.Tooltip("value:Q", format=",.4f")],
            )
            .properties(height=300)
        )
        st.altair_chart(chart)
