"""Chart helpers shared by all pages."""

import altair as alt
import pandas as pd
import streamlit as st


def stacked_bars(df: pd.DataFrame, group_col: str, y_title: str, legend: str, fmt: str = ",.2f", height: int = 320) -> None:
    """Stacked bars from per_period() output (columns: period, group_col, value)."""
    if df.empty or df["value"].sum() == 0:
        st.info("No data in this period.")
        return
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("period:N", title=None, sort=None),
            y=alt.Y("value:Q", title=y_title, stack="zero"),
            color=alt.Color(f"{group_col}:N", title=legend),
            tooltip=[
                alt.Tooltip("period:N", title="Period"),
                alt.Tooltip(f"{group_col}:N", title=legend),
                alt.Tooltip("value:Q", title=y_title, format=fmt),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart)


def lines(df: pd.DataFrame, group_col: str, y_title: str, legend: str, fmt: str = ",.1f", height: int = 320) -> None:
    """Lines from per_period() output; NaN values leave gaps instead of dropping to zero."""
    if df.empty or df["value"].isna().all():
        st.info("No data in this period.")
        return
    chart = (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("period:N", title=None, sort=None),
            y=alt.Y("value:Q", title=y_title),
            color=alt.Color(f"{group_col}:N", title=legend),
            tooltip=[
                alt.Tooltip("period:N", title="Period"),
                alt.Tooltip(f"{group_col}:N", title=legend),
                alt.Tooltip("value:Q", title=y_title, format=fmt),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart)
