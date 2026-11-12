import streamlit as st

import charts
import data

f = data.filters()
data.page_title("Performance", ":material/speed:", f)

req = data.filter_requests(data.load_requests(), f)
if req.empty:
    st.warning("No agent usage in this period.")
    st.stop()

req = req.assign(agent_name=req["agent_name"].map(data.display_name))
st.caption(
    "Response time = END_TIME minus START_TIME of a request, i.e. how long the agent worked on it "
    "(planning, tool calls, answer)."
)


def p90(s):
    return s.quantile(0.9)


# ---------------------------------------------------------------------------
st.subheader("Response time by agent")
latency = (
    req.groupby("agent_name")["duration_s"]
    .agg(requests="count", p50="median", p90=p90, max="max")
    .reset_index()
    .sort_values("p90", ascending=False)
)
st.dataframe(
    latency,
    hide_index=True,
    column_config={
        "agent_name": "Agent",
        "requests": "Requests",
        "p50": st.column_config.NumberColumn("Median (s)", format="%.0f"),
        "p90": st.column_config.NumberColumn("p90 (s)", format="%.0f"),
        "max": st.column_config.NumberColumn("Max (s)", format="%.0f"),
    },
)

st.subheader("p90 response time over time")
charts.lines(data.per_period(req, "duration_s", "agent_name", f, agg=p90), "agent_name", "p90 (s)", "Agent", fmt=",.0f")

# ---------------------------------------------------------------------------
st.subheader("Agent versions")
st.caption("Cost and speed per agent version, to check whether a new version got cheaper, faster or slower.")
versions = (
    req.groupby(["agent_name", "agent_version"])
    .agg(
        live=("version_is_default", "max"),
        first_use=("start_time", "min"),
        last_use=("start_time", "max"),
        requests=("request_id", "nunique"),
        credits=("token_credits", "sum"),
        p50=("duration_s", "median"),
        p90=("duration_s", p90),
    )
    .reset_index()
    .sort_values(["agent_name", "first_use"])
)
versions["credits_per_request"] = versions["credits"] / versions["requests"]
st.dataframe(
    versions.drop(columns="credits"),
    hide_index=True,
    column_order=[
        "agent_name", "agent_version", "live", "first_use", "last_use",
        "requests", "credits_per_request", "p50", "p90",
    ],
    column_config={
        "agent_name": "Agent",
        "agent_version": "Version",
        "live": st.column_config.CheckboxColumn("Default", help="Version is the agent's default version"),
        "first_use": st.column_config.DatetimeColumn("First use", format="YYYY-MM-DD"),
        "last_use": st.column_config.DatetimeColumn("Last use", format="YYYY-MM-DD"),
        "requests": "Requests",
        "credits_per_request": st.column_config.NumberColumn("AI credits / request", format="%.3f"),
        "p50": st.column_config.NumberColumn("Median (s)", format="%.0f"),
        "p90": st.column_config.NumberColumn("p90 (s)", format="%.0f"),
    },
)
