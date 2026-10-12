"""
Real-Time Theft & Intrusion Detection
Streamlit entry point. Run with: streamlit run app.py
"""
import base64
import os
import time

import cv2

import pandas as pd
import streamlit as st

import config
from core.video_processor import VideoProcessor
from database.db_manager import DBManager
from ui.styles import inject_custom_css, alert_card_html
from ui.zone_editor import render_zone_editor, load_zones
from ui.analytics import render_analytics
from ui.agent_page import render_agent_page
from ui.about_page import render_about_page

st.set_page_config(page_title=config.APP_TITLE, page_icon="🛡️", layout="wide")
inject_custom_css()

if "processor" not in st.session_state:
    st.session_state.processor = None
if "recent_alerts" not in st.session_state:
    st.session_state.recent_alerts = []


def get_db():
    if "db" not in st.session_state:
        st.session_state.db = DBManager(config.DB_PATH)
    return st.session_state.db


def ensure_demo_video():
    """Return a local path to the demo clip, downloading it once if it is not bundled."""
    if os.path.isfile(config.DEMO_VIDEO_PATH) and os.path.getsize(config.DEMO_VIDEO_PATH) > 100_000:
        return config.DEMO_VIDEO_PATH
    import requests
    st.sidebar.info("Downloading demo video (first time only, ~10 s)…")
    os.makedirs(os.path.dirname(config.DEMO_VIDEO_PATH), exist_ok=True)
    tmp = config.DEMO_VIDEO_PATH + ".part"
    for url in config.DEMO_VIDEO_URLS:
        try:
            with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "Mozilla/5.0"}) as r:
                if r.status_code != 200:
                    continue
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            if os.path.getsize(tmp) > 100_000:
                os.replace(tmp, config.DEMO_VIDEO_PATH)
                return config.DEMO_VIDEO_PATH
        except Exception:
            continue
    st.sidebar.error("Could not download the demo video. Please use 'Upload video' instead.")
    return None


# ---------- Sidebar ----------
st.sidebar.title(f"🛡️ {config.APP_NAME}")
st.sidebar.caption(config.APP_TAGLINE)
page = st.sidebar.radio(
    "Navigate",
    ["Live monitor", "AI Agent", "Zone setup", "Alerts log", "Analytics", "About project", "Settings"],
)

st.sidebar.divider()
st.sidebar.subheader("Video source")
source_options = ([] if config.IS_CLOUD else ["Webcam"]) + ["Demo video", "Upload video"]
source_type = st.sidebar.radio("Source type", source_options, horizontal=True)
if config.IS_CLOUD:
    st.sidebar.caption("Cloud mode: a server has no webcam, so use the demo clip or upload CCTV footage.")

video_source = None
if source_type == "Webcam":
    cam_index = st.sidebar.number_input("Webcam index", min_value=0, max_value=10, value=0)
    video_source = int(cam_index)
elif source_type == "Demo video":
    video_source = ensure_demo_video()
    st.sidebar.caption(config.DEMO_VIDEO_CREDIT)
else:
    uploaded = st.sidebar.file_uploader("Upload a video file", type=["mp4", "avi", "mov", "mkv"])
    if uploaded is not None:
        if uploaded.size > config.MAX_UPLOAD_MB * 1024 * 1024:
            st.sidebar.error(f"File too large (max {config.MAX_UPLOAD_MB} MB).")
        else:
            safe_name = "".join(c for c in uploaded.name if c.isalnum() or c in "._-")
            temp_path = os.path.join(config.DATA_DIR, "uploaded_" + safe_name)
            if not os.path.isfile(temp_path) or os.path.getsize(temp_path) != uploaded.size:
                with open(temp_path, "wb") as f:
                    f.write(uploaded.getbuffer())
            video_source = temp_path

loop_video = st.sidebar.checkbox("Loop video", value=True, disabled=source_type == "Webcam",
                                 help="Restart the clip when it ends, so the demo keeps running.")

st.sidebar.subheader("Detection settings")
confidence = st.sidebar.slider("Confidence threshold", 0.1, 0.9, config.DEFAULT_CONFIDENCE, 0.05)
iou = st.sidebar.slider("IoU threshold", 0.1, 0.9, config.DEFAULT_IOU, 0.05)


# ---------- Live monitor ----------
def live_monitor_page():
    st.header("Live monitor")

    col_a, col_b, _ = st.columns([1, 1, 4])
    disabled = video_source is None
    start_clicked = col_a.button("Start monitoring", type="primary", disabled=disabled)
    stop_clicked = col_b.button("Stop monitoring")

    if start_clicked:
        if st.session_state.processor is not None and st.session_state.processor.is_running():
            st.session_state.processor.stop()
        zones = load_zones()
        processor = VideoProcessor(source=video_source, zones=zones, confidence=confidence, iou=iou,
                                   loop=loop_video)
        try:
            processor.start()
            st.session_state.processor = processor
            st.session_state.recent_alerts = []
            # Fresh monitoring session -> let the fragment recreate its
            # placeholders once, instead of reusing stale ones.
            for key in ("live_frame_slot", "live_metrics_slot", "live_alerts_slot"):
                st.session_state.pop(key, None)
        except RuntimeError as exc:
            st.error(str(exc))

    if stop_clicked and st.session_state.processor is not None:
        st.session_state.processor.stop()

    processor = st.session_state.processor

    if processor is None or not processor.is_running():
        st.info("Monitoring is stopped. Configure a source in the sidebar and click 'Start monitoring'.")
        return

    _live_fragment(processor)


@st.fragment(run_every=0.5 if config.IS_CLOUD else 0.2)
def _live_fragment(processor):
    # Create the placeholders only ONCE per monitoring session (cached in
    # session_state), then reuse the same objects on every fragment tick.
    # Reusing the same placeholder updates it in place instead of replacing
    # the whole element, which is what removes the flash/flicker.
    if "live_frame_slot" not in st.session_state:
        st.session_state.live_frame_slot = st.empty()
        st.session_state.live_metrics_slot = st.empty()
        st.session_state.live_alerts_slot = st.empty()

    frame_slot = st.session_state.live_frame_slot
    metrics_slot = st.session_state.live_metrics_slot
    alerts_slot = st.session_state.live_alerts_slot

    if not processor.is_running():
        frame_slot.warning("Video source ended or disconnected.")
        return

    frame, _, stats = processor.get_state()
    alerts = processor.pop_alerts()

    if frame is not None:
        # Embed the frame inline (base64) instead of st.image: on cloud hosting, rapidly
        # replaced st.image media files can be deleted before the browser fetches them (404).
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            b64 = base64.b64encode(buf.tobytes()).decode()
            frame_slot.markdown(
                f'<img src="data:image/jpeg;base64,{b64}" style="width:100%;border-radius:10px" alt="live frame"/>',
                unsafe_allow_html=True,
            )

    with metrics_slot.container():
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("FPS", stats.get("fps", 0))
        c2.metric("People detected", stats.get("people_count", 0))
        c3.metric("Objects tracked", stats.get("object_count", 0))
        c4.metric("Total alerts (session)", stats.get("total_alerts", 0))

    for inc in processor.pop_incidents():
        st.toast(f"🤖 Incident Agent: {inc.title} (risk {inc.risk_score})", icon="🚨")
        st.session_state.recent_alerts.insert(0, {
            "message": f"🤖 AGENT INCIDENT — {inc.title} · risk {inc.risk_score}/100 · {inc.action_taken}",
            "severity": inc.severity, "timestamp": inc.timestamp,
        })

    if alerts:
        st.session_state.recent_alerts = (
            [{"message": a.message, "severity": a.severity, "timestamp": a.timestamp} for a in alerts]
            + st.session_state.recent_alerts
        )[:20]

    with alerts_slot.container():
        st.subheader("Recent alerts")
        if not st.session_state.recent_alerts:
            st.caption("No alerts yet.")
        for row in st.session_state.recent_alerts[:8]:
            st.markdown(alert_card_html(row), unsafe_allow_html=True)


def zone_setup_page():
    if video_source is None:
        st.header("Zone setup")
        st.info("Select the demo video or upload a video in the sidebar first, then capture a frame from it.")
        return
    render_zone_editor(video_source)


def alerts_log_page():
    st.header("Alerts log")
    db = get_db()

    col1, col2, col3 = st.columns(3)
    rule_filter = col1.selectbox("Event type", ["All", "zone_intrusion", "loitering", "running", "object_removed"])
    severity_filter = col2.selectbox("Severity", ["All", "info", "warning", "critical"])
    limit = col3.number_input("Max rows", min_value=10, max_value=1000, value=100, step=10)

    events = db.fetch_events(
        limit=limit,
        rule=None if rule_filter == "All" else rule_filter,
        severity=None if severity_filter == "All" else severity_filter,
    )

    if not events:
        st.info("No events match the current filters.")
        return

    df = pd.DataFrame(events)
    df["time"] = pd.to_datetime(df["timestamp"], unit="s")
    st.dataframe(
        df[["time", "rule", "zone", "severity", "message", "track_id"]],
        width="stretch", hide_index=True,
    )

    with st.expander("View snapshots"):
        for e in events[:20]:
            if e.get("snapshot_path") and os.path.isfile(e["snapshot_path"]):
                st.image(e["snapshot_path"], caption=e["message"], width=320)


def analytics_page():
    st.header("Analytics")
    render_analytics(get_db())


def settings_page():
    st.header("Settings")
    st.write("Database path:", config.DB_PATH)
    st.write("Model weights:", config.MODEL_WEIGHTS)
    st.write("Snapshots directory:", config.SNAPSHOTS_DIR)
    st.divider()
    st.subheader("AI agent connection")
    from agent.llm_client import LLMClient, LLMUnavailable
    client = LLMClient()
    st.write("Configured:", client.describe())
    if st.button("Test AI connection"):
        try:
            with st.spinner("Calling the LLM…"):
                reply = client.chat([{"role": "user", "content": "Reply with exactly: Sentinel online"}], timeout=30)
            st.success(f"Connected via {client.describe()} — reply: {reply.get('content')}")
        except LLMUnavailable as exc:
            st.error(f"Not connected. Details: {exc}")
    st.divider()
    st.subheader("Behavior thresholds (edit config.py to change permanently)")
    st.json({
        "LOITER_SECONDS": config.LOITER_SECONDS,
        "RUN_SPEED_PX_PER_SEC": config.RUN_SPEED_PX_PER_SEC,
        "OBJECT_MISSING_FRAMES": config.OBJECT_MISSING_FRAMES,
        "ALERT_COOLDOWN_SECONDS": config.ALERT_COOLDOWN_SECONDS,
    })


PAGES = {
    "Live monitor": live_monitor_page,
    "Zone setup": zone_setup_page,
    "Alerts log": alerts_log_page,
    "AI Agent": lambda: render_agent_page(get_db()),
    "Analytics": analytics_page,
    "About project": render_about_page,
    "Settings": settings_page,
}
PAGES[page]()
