import pandas as pd
import streamlit as st

import charts
import data

f = data.filters()
data.page_title("Adoption", ":material/group:", f)

history = data.load_requests()
if f.agent:
    history = history[history["agent_name"] == f.agent]
req = data.filter_requests(history, f)
if req.empty:
    st.warning("No agent usage in this period.")
    st.stop()

# First use over the full history, so users active before the period are not counted as new
first_use = history.groupby("user_name")["usage_date"].min()
new_users = int((first_use.between(f.start, f.end)).sum())
active = req["user_name"].nunique()
conversations = req["conversation_id"].nunique()

with st.container(horizontal=True):
    st.metric("Active users", f"{active:,}", border=True)
    st.metric("New users", f"{new_users:,}", border=True, help="First request ever falls in this period")
    st.metric("Returning users", f"{active - new_users:,}", border=True)
    st.metric("Requests / conversation", f"{req['request_id'].nunique() / conversations:.1f}", border=True)
    st.metric("Agents in use", f"{req['agent_name'].nunique():,}", border=True)

# ---------------------------------------------------------------------------
st.subheader("Active users: new vs returning")
st.caption("A user counts as new in the period of their first request ever, returning in every later one.")
first_period = data.period_of(first_use, f.days).rename("first_period")
active_users = (
    req.assign(period=data.period_of(req["usage_date"], f.days))[["period", "user_name"]]
    .drop_duplicates()
    .join(first_period, on="user_name")
)
active_users["user_type"] = (active_users["period"] == active_users["first_period"]).map(
    {True: "New", False: "Returning"}
)
counts = active_users.groupby(["period", "user_type"]).size().rename("value").reset_index()
grid = pd.MultiIndex.from_product([data.periods(f), ["New", "Returning"]], names=["period", "user_type"])
counts = grid.to_frame(index=False).merge(counts, how="left").fillna({"value": 0})
charts.stacked_bars(counts, "user_type", "Active users", "User", fmt=",.0f")

# ---------------------------------------------------------------------------
st.subheader("Active users by agent")
plot = req.assign(agent_name=req["agent_name"].map(data.display_name))
charts.stacked_bars(
    data.per_period(plot, "user_name", "agent_name", f, agg="nunique"), "agent_name", "Active users", "Agent", fmt=",.0f"
)

st.subheader("Engagement by agent")
engagement = (
    plot.groupby("agent_name")
    .agg(
        users=("user_name", "nunique"),
        requests=("request_id", "nunique"),
        conversations=("conversation_id", "nunique"),
        active_days=("usage_date", "nunique"),
    )
    .reset_index()
)
engagement["requests_per_user"] = engagement["requests"] / engagement["users"]
engagement["requests_per_conversation"] = engagement["requests"] / engagement["conversations"]
st.dataframe(
    engagement.sort_values("users", ascending=False),
    hide_index=True,
    column_config={
        "agent_name": "Agent",
        "users": "Users",
        "requests": "Requests",
        "conversations": "Conversations",
        "active_days": "Active days",
        "requests_per_user": st.column_config.NumberColumn("Requests / user", format="%.1f"),
        "requests_per_conversation": st.column_config.NumberColumn("Requests / conversation", format="%.1f"),
    },
)
