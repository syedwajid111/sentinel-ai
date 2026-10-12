"""
Central configuration for the surveillance system.
Edit these values to tune detection, behavior rules, and storage paths.
"""
import os
import time

# All timestamps are shown in Pakistan time, also on cloud servers (which run in UTC)
os.environ.setdefault("TZ", "Asia/Karachi")
if hasattr(time, "tzset"):
    time.tzset()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Paths ---
MODELS_DIR = os.path.join(BASE_DIR, "models")
DATA_DIR = os.path.join(BASE_DIR, "data")
SNAPSHOTS_DIR = os.path.join(DATA_DIR, "snapshots")
RECORDINGS_DIR = os.path.join(DATA_DIR, "recordings")
DB_PATH = os.path.join(DATA_DIR, "events.db")
ZONES_PATH = os.path.join(BASE_DIR, "zones.json")

for _dir in (MODELS_DIR, SNAPSHOTS_DIR, RECORDINGS_DIR):
    os.makedirs(_dir, exist_ok=True)

# --- Deployment mode ---
# On Hugging Face Spaces (or any server) there is no webcam, so the app switches to
# "cloud mode": video upload / demo video only. SPACE_ID is set automatically by HF.
# Streamlit Community Cloud mounts the repo under /mount/src
IS_CLOUD = (bool(os.getenv("SPACE_ID")) or os.path.isdir("/mount/src")
            or os.getenv("SENTINEL_CLOUD", "0") == "1")
DEMO_VIDEO_PATH = os.path.join(BASE_DIR, "assets", "demo.mp4")
# If assets/demo.mp4 is not in the repo, the app downloads this free-licensed clip on first use
# ("Thief Stealing Handbag from a Car" — Pexels, free to use: https://www.pexels.com/video/854221/)
DEMO_VIDEO_URLS = [
    "https://videos.pexels.com/video-files/854221/854221-sd_960_540_24fps.mp4",
    "https://videos.pexels.com/video-files/854221/854221-hd_1280_720_24fps.mp4",
    "https://videos.pexels.com/video-files/854221/854221-hd_1920_1080_24fps.mp4",
]
DEMO_VIDEO_CREDIT = "Demo clip: “Thief Stealing Handbag from a Car” — Pexels (free license)"
MAX_UPLOAD_MB = 200

# --- Model ---
MODEL_WEIGHTS = os.path.join(MODELS_DIR, "yolov8n.pt")  # falls back to auto-download if missing
DEFAULT_CONFIDENCE = 0.45
DEFAULT_IOU = 0.45
TRACKER_CONFIG = "bytetrack.yaml"

# Only these COCO classes matter for a surveillance/theft-risk scenario
MONITORED_CLASSES = {
    0: "person",
    24: "backpack",
    26: "handbag",
    28: "suitcase",
    63: "laptop",
    67: "cell phone",
}
PERSON_CLASS_ID = 0
VALUABLE_OBJECT_CLASS_IDS = {24, 26, 28, 63, 67}

# --- Preprocessing ---
FRAME_WIDTH = 960
FRAME_HEIGHT = 540
APPLY_DENOISE = True

# --- Behavior rules ---
LOITER_SECONDS = 8.0             # time inside a zone before flagging loitering
RUN_SPEED_PX_PER_SEC = 550       # centroid speed threshold for "running"
OBJECT_MISSING_FRAMES = 8       # frames a tracked object must vanish for before flagging removal
OBJECT_MIN_PRESENCE_FRAMES = 5  # frames an object must be stably tracked before it "counts"
PERSON_PROXIMITY_PX = 120        # distance within which a person is considered "near" an object

# --- Alerts ---
ALERT_COOLDOWN_SECONDS = 10      # per track_id+rule, avoid duplicate alert spam
ENABLE_SOUND_ALERTS = not IS_CLOUD
# Email settings come from environment variables / HF Space secrets (never hard-code passwords)
SMTP_SERVER = os.getenv("SMTP_SERVER", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
ENABLE_EMAIL_ALERTS = bool(SMTP_SERVER and ALERT_EMAIL_TO)

# --- AI Agent layer ---
# Incident Agent (autonomous, offline): links alerts into incidents
INCIDENT_LOOKBACK_SECONDS = 600   # how far back it looks when a new alert arrives
INCIDENT_LINK_SECONDS = 60        # max gap between linked alerts (e.g. loitering -> object removed)
INCIDENT_LOITER_REPEAT = 3        # loitering alerts in one zone before "possible casing"
INCIDENT_CROWD_PEOPLE = 3         # distinct people in one restricted zone before "zone crowding"
# Sentinel AI Agent (LLM): set GEMINI_API_KEY or GROQ_API_KEY as an environment variable / HF secret
AGENT_MAX_STEPS = 5

# --- UI ---
APP_NAME = "Sentinel AI"
APP_TITLE = "Sentinel AI — Agent-Based Theft & Intrusion Detection"
APP_TAGLINE = "Real-time CCTV analytics with an autonomous AI security agent"
TEAM_MEMBERS = ["CO", "Kanza", "Fiza"]   # TODO: replace with full names + roll numbers
INSTITUTE = "BSCS Final Year Project"
THEME_ACCENT = "#3B82F6"
