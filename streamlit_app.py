import streamlit as st

import data

st.set_page_config(page_title="CoWork Agents Monitor", page_icon=":material/monitoring:", layout="wide")

page = st.navigation(
    [
        st.Page("app_pages/overview.py", title="Overview", icon=":material/monitoring:", default=True),
        st.Page("app_pages/cost.py", title="Cost & compute", icon=":material/payments:"),
        st.Page("app_pages/performance.py", title="Performance", icon=":material/speed:"),
        st.Page("app_pages/adoption.py", title="Adoption", icon=":material/group:"),
    ],
    position="top",
)

# Shared filters, kept in session state so they persist across pages
requests = data.load_requests()
agents = sorted(requests["agent_name"].unique())

st.sidebar.header("Filters")
st.sidebar.segmented_control("Time range", list(data.TIME_RANGES), key="range", default="2 weeks")
if st.session_state.get("agent") not in [data.ALL_AGENTS, *agents]:
    st.session_state.agent = data.ALL_AGENTS
st.sidebar.selectbox("Agent", [data.ALL_AGENTS, *agents], key="agent", format_func=data.display_name)
st.sidebar.toggle("Show costs", value=True, key="show_costs", help="Turn off for a management view without costs.")

st.sidebar.divider()
if st.sidebar.button(":material/refresh: Refresh data", width="stretch"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption("ACCOUNT_USAGE views can lag by up to a few hours.")

page.run()
