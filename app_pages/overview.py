import streamlit as st

import charts
import data

f = data.filters()
data.page_title("Agent usage", ":material/monitoring:", f)

req = data.filter_requests(data.load_requests(), f)
if req.empty:
    st.warning("No agent usage in this period.")
    st.stop()

credits = req["token_credits"].sum()
with st.container(horizontal=True):
    st.metric("AI credits", f"{credits:,.2f}", border=True)
    if f.show_costs:
        st.metric("Est. cost", data.money(credits, "ai"), border=True)
    else:
        st.metric("Tokens", f"{req['tokens'].sum():,}", border=True)
    st.metric("Requests", f"{req['request_id'].nunique():,}", border=True)
    st.metric("Conversations", f"{req['conversation_id'].nunique():,}", border=True)
    st.metric("Users", f"{req['user_name'].nunique():,}", border=True)

group_col = "user_name" if f.agent else "agent_name"
legend = "User" if f.agent else "Agent"
plot = req.assign(agent_name=req["agent_name"].map(data.display_name))

if f.show_costs:
    st.subheader(f"AI credits by {legend.lower()}")
    charts.stacked_bars(data.per_period(plot, "token_credits", group_col, f), group_col, "AI credits", legend)
else:
    st.subheader(f"Requests by {legend.lower()}")
    charts.stacked_bars(
        data.per_period(plot, "request_id", group_col, f, agg="nunique"), group_col, "Requests", legend, fmt=",.0f"
    )

st.subheader(f"Usage by {legend.lower()}")
table = (
    plot.groupby(group_col)
    .agg(
        credits=("token_credits", "sum"),
        tokens=("tokens", "sum"),
        requests=("request_id", "nunique"),
        api_requests=("channel", lambda s: int((s == "API").sum())),
        conversations=("conversation_id", "nunique"),
        users=("user_name", "nunique"),
        first_use=("start_time", "min"),
        last_use=("start_time", "max"),
    )
    .reset_index()
    .sort_values("credits", ascending=False)
)
if f.agent:
    table = table.drop(columns="users")
if f.show_costs:
    table.insert(2, "cost", table["credits"].map(lambda c: data.money(c, "ai")))

st.dataframe(
    table,
    hide_index=True,
    column_config={
        "agent_name": "Agent",
        "user_name": "User",
        "credits": st.column_config.NumberColumn("AI credits", format="%.2f"),
        "cost": "Est. cost",
        "tokens": st.column_config.NumberColumn("Tokens", format="localized"),
        "requests": "Requests",
        "api_requests": st.column_config.NumberColumn("Via API", help="Direct Cortex Agent API calls, not through CoWork"),
        "conversations": "Conversations",
        "users": "Users",
        "first_use": st.column_config.DatetimeColumn("First use", format="YYYY-MM-DD HH:mm"),
        "last_use": st.column_config.DatetimeColumn("Last use", format="YYYY-MM-DD HH:mm"),
    },
)
