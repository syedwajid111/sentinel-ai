"""About page: what the project is, how it works, who built it (for examiners / visitors)."""
import streamlit as st

import config

ARCHITECTURE = """
```
 Camera / CCTV video
        │
        ▼
 [1] Pre-processing (OpenCV)      resize 960×540 · Gaussian denoise
        │
        ▼
 [2] Detection  (YOLOv8n)         person · bag · suitcase · laptop · phone
        │
        ▼
 [3] Tracking   (ByteTrack)       stable IDs, speed, dwell time per person
        │
        ▼
 [4] Behaviour rule engine        zone intrusion · loitering · running · object removed
        │  alerts → SQLite + snapshots
        ▼
 [5] Incident Agent (autonomous)  links alerts into threats + risk score → acts (escalate / email)
        │
        ▼
 [6] Sentinel Analyst (LLM agent) tool-calling: answers questions, writes shift reports
        │
        ▼
 Streamlit dashboard  ·  live monitor · AI agent · analytics · alerts log
```
"""


def render_about_page():
    st.header(f"🛡️ {config.APP_NAME}")
    st.subheader(config.APP_TAGLINE)
    st.markdown(
        "Ordinary CCTV only **records**; someone has to watch hours of footage to find a theft after it happened. "
        f"**{config.APP_NAME}** watches the feed for you: computer vision detects and tracks people and valuables, "
        "a rule engine flags risky behaviour, and two AI agents turn those alerts into decisions, explanations "
        "and reports."
    )

    st.markdown("### System architecture")
    st.markdown(ARCHITECTURE)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Why it is agent-based")
        st.markdown(
            "- **Perceives**: reads every new alert from the vision pipeline\n"
            "- **Reasons**: correlates alerts over time (e.g. loitering → item gone → running = probable theft) "
            "and assigns a 0-100 risk score with a written justification\n"
            "- **Acts on its own**: escalates critical incidents, sends notifications, keeps a watch-list\n"
            "- **Uses tools**: the analyst agent decides which database tools to call to answer a question — "
            "its answers are grounded in real data, not guessed\n"
            "- **Explains itself**: every answer shows the tool calls it made"
        )
    with c2:
        st.markdown("### Tech stack")
        st.markdown(
            "- Python · OpenCV · Ultralytics YOLOv8 · ByteTrack\n"
            "- SQLite event & incident store\n"
            "- LLM via OpenAI-compatible API (Gemini / Groq) with offline fallback\n"
            "- Streamlit + Plotly dashboard\n"
            "- Streamlit Community Cloud (cloud hosting)"
        )

    st.markdown("### Team")
    cols = st.columns(len(config.TEAM_MEMBERS))
    for col, name in zip(cols, config.TEAM_MEMBERS):
        col.markdown(f"<div class='alert-card'><b>{name}</b></div>", unsafe_allow_html=True)
    st.caption(config.INSTITUTE)

    st.markdown("### Honest limitations")
    st.markdown(
        "- The system flags **patterns associated with** theft; it cannot prove a crime. A human verifies.\n"
        "- YOLOv8n is the smallest model (fast on CPU); accuracy drops in very dark or crowded scenes.\n"
        "- In the cloud demo there is no webcam; live camera mode runs on a local machine."
    )
