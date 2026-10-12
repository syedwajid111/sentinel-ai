"""AI Agent page: chat with Sentinel, see incidents it raised, generate shift reports."""
import time

import pandas as pd
import streamlit as st

from agent.demo_data import load_demo_shift
from agent.sentinel_agent import SentinelAgent

QUICK_PROMPTS = [
    "Give me today's security summary",
    "Was there any possible theft?",
    "Which zone is the most risky?",
    "What did person #14 do?",
    "Aaj kitne critical alerts aaye?",
]


def _agent(db):
    if "sentinel_agent" not in st.session_state:
        st.session_state.sentinel_agent = SentinelAgent(db)
    return st.session_state.sentinel_agent


def render_agent_page(db):
    agent = _agent(db)
    st.header("🤖 Sentinel AI Agent")
    st.caption(
        "Two agents work together: the **Incident Agent** runs automatically on every alert and links "
        "alerts into threats with a risk score; the **Sentinel Analyst** answers questions and writes reports "
        "by calling tools on the live event database."
    )
    mode = agent.llm.describe()
    st.markdown(f"<span class='badge badge-info'>engine</span> {mode}", unsafe_allow_html=True)

    tab_chat, tab_inc, tab_report = st.tabs(["💬 Ask the agent", "🚨 Incidents", "📄 Shift report"])

    with tab_chat:
        _chat_tab(agent)
    with tab_inc:
        _incidents_tab(db)
    with tab_report:
        _report_tab(agent)

    with st.expander("Demo data (for presentations)"):
        st.caption("Loads one simulated shift of alerts so the agent can be demonstrated without running a video. "
                   "Real monitoring data is added on top.")
        c1, c2 = st.columns(2)
        if c1.button("Load demo shift"):
            n_ev, n_inc = load_demo_shift(db)
            st.success(f"Loaded {n_ev} demo alerts — the Incident Agent raised {n_inc} incident(s).")
        if c2.button("Clear all alerts & incidents"):
            db.clear_all()
            st.session_state.agent_chat = []
            st.success("Database cleared.")


def _chat_tab(agent):
    st.session_state.setdefault("agent_chat", [])
    history = st.session_state.agent_chat

    cols = st.columns(len(QUICK_PROMPTS))
    clicked = None
    for col, prompt in zip(cols, QUICK_PROMPTS):
        if col.button(prompt, width="stretch"):
            clicked = prompt

    for turn in history:
        with st.chat_message(turn["role"], avatar="🛡️" if turn["role"] == "assistant" else None):
            st.markdown(turn["content"])
            _render_steps(turn.get("steps"), turn.get("mode"), turn.get("note"))

    question = st.chat_input("Ask about alerts, incidents, zones, people… (English or Roman Urdu)") or clicked
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant", avatar="🛡️"):
            with st.spinner("Agent is thinking and calling tools…"):
                result = agent.ask(question, history=[{"role": t["role"], "content": t["content"]} for t in history])
            st.markdown(result.answer)
            steps = [{"tool": s.tool, "arguments": s.arguments, "result": s.result_preview} for s in result.steps]
            _render_steps(steps, result.mode, result.note)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": result.answer, "steps": steps,
                        "mode": result.mode, "note": result.note})

    if history and st.button("Clear conversation"):
        st.session_state.agent_chat = []
        st.rerun()


def _render_steps(steps, mode, note):
    if note:
        st.caption(f"ℹ️ {note}")
    if steps:
        with st.expander(f"Agent reasoning — {len(steps)} tool call(s) · {mode}"):
            for i, s in enumerate(steps, 1):
                st.markdown(f"**{i}. `{s['tool']}`** `{s['arguments']}`")
                st.code(s["result"], language="json")


def _incidents_tab(db):
    incidents = db.fetch_incidents(limit=200)
    if not incidents:
        st.info("No incidents yet. They appear automatically when alerts form a threat pattern "
                "(e.g. loitering → item removed → running).")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Incidents", len(incidents))
    c2.metric("Critical", sum(1 for i in incidents if i["severity"] == "critical"))
    c3.metric("Highest risk", f"{max(i['risk_score'] for i in incidents)}/100")
    for inc in incidents[:30]:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(inc["timestamp"]))
        sev = inc["severity"]
        st.markdown(
            f"<div class='alert-card alert-{sev}'><span class='badge badge-{sev}'>risk {inc['risk_score']}</span>"
            f"<b>{inc['title']}</b><br><small>{ts} · zone: {inc['zone'] or '—'} · linked alerts: "
            f"{inc['event_ids']}</small><br>{inc['reasoning']}<br><i>Action: {inc['action_taken']}</i></div>",
            unsafe_allow_html=True,
        )
    with st.expander("Table view"):
        df = pd.DataFrame(incidents)
        df["time"] = pd.to_datetime(df["timestamp"], unit="s")
        st.dataframe(df[["time", "risk_score", "severity", "title", "zone", "action_taken"]],
                     width="stretch", hide_index=True)


def _report_tab(agent):
    hours = st.select_slider("Report period", options=[1, 6, 12, 24, 48, 168], value=24,
                             format_func=lambda h: f"last {h} h" if h < 168 else "last 7 days")
    if st.button("Generate shift report", type="primary"):
        with st.spinner("Agent is collecting data and writing the report…"):
            st.session_state.agent_report = agent.generate_report(hours)
    result = st.session_state.get("agent_report")
    if result:
        if result.note:
            st.caption(f"ℹ️ {result.note}")
        st.download_button("Download report (.md)", result.answer,
                           file_name=time.strftime("sentinel_report_%Y%m%d_%H%M.md"), mime="text/markdown")
        st.markdown(result.answer)
