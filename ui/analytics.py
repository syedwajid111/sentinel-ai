"""Charts and KPIs for the Analytics page, built with Plotly."""
import pandas as pd
import plotly.express as px
import streamlit as st


def render_analytics(db):
    events = db.fetch_events(limit=2000)
    total = db.total_count()
    by_rule = db.stats_by_rule()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total alerts", total)
    col2.metric("Most frequent event", by_rule[0]["rule"] if by_rule else "—")
    critical_count = sum(1 for e in events if e["severity"] == "critical")
    col3.metric("Critical alerts (recent)", critical_count)

    if not events:
        st.info("No events logged yet. Alerts will appear here once monitoring starts.")
        return

    df = pd.DataFrame(events)
    df["time"] = pd.to_datetime(df["timestamp"], unit="s")

    st.subheader("Alerts over time")
    timeline = (
        df.groupby([pd.Grouper(key="time", freq="1min"), "severity"])
        .size()
        .reset_index(name="count")
    )
    fig1 = px.bar(
        timeline, x="time", y="count", color="severity",
        color_discrete_map={"critical": "#E24B4A", "warning": "#EF9F27", "info": "#378ADD"},
    )
    fig1.update_layout(template="plotly_dark", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig1, width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Events by type")
        rule_df = pd.DataFrame(by_rule)
        fig2 = px.pie(rule_df, names="rule", values="count", hole=0.45)
        fig2.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig2, width="stretch")

    with c2:
        st.subheader("Events by zone")
        zone_df = pd.DataFrame(db.stats_by_zone())
        if not zone_df.empty:
            fig3 = px.bar(zone_df, x="zone", y="count")
            fig3.update_layout(template="plotly_dark", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig3, width="stretch")
        else:
            st.caption("No zone-specific events yet.")
