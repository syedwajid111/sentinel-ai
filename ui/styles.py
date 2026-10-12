"""Custom CSS injected into the Streamlit app for a polished look."""
import streamlit as st

import config


def inject_custom_css():
    st.markdown(f"""
    <style>
        .stApp {{
            background-color: #0E1117;
        }}
        [data-testid="stSidebar"] {{
            background-color: #131722;
            border-right: 1px solid #262b3d;
        }}
        div[data-testid="stMetric"] {{
            background-color: #1A1F2E;
            border: 1px solid #262b3d;
            border-radius: 10px;
            padding: 14px 16px;
        }}
        .alert-card {{
            border-radius: 8px;
            padding: 10px 14px;
            margin-bottom: 8px;
            border-left: 4px solid {config.THEME_ACCENT};
            background-color: #1A1F2E;
            font-size: 14px;
        }}
        .alert-critical {{ border-left-color: #E24B4A; }}
        .alert-warning  {{ border-left-color: #EF9F27; }}
        .alert-info     {{ border-left-color: #378ADD; }}
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            margin-right: 6px;
        }}
        .badge-critical {{ background-color: #4A1313; color: #F09595; }}
        .badge-warning  {{ background-color: #412402; color: #FAC775; }}
        .badge-info     {{ background-color: #042C53; color: #85B7EB; }}
        h1, h2, h3 {{ font-weight: 500; }}
    </style>
    """, unsafe_allow_html=True)


def alert_card_html(alert_row):
    severity = alert_row.get("severity", "info")
    ts = alert_row.get("timestamp")
    import time as _time
    ts_str = _time.strftime("%H:%M:%S", _time.localtime(ts)) if ts else ""
    return f"""
    <div class="alert-card alert-{severity}">
        <span class="badge badge-{severity}">{severity}</span>
        <b>{ts_str}</b> &nbsp; {alert_row.get('message', '')}
    </div>
    """
