# Sentinel AI — Agent-Based Theft & Intrusion Detection

BSCS Final Year Project. Real-time CCTV analytics with an autonomous AI security agent.

**Pipeline:** OpenCV preprocessing → YOLOv8n detection → ByteTrack tracking → behaviour rules
(zone intrusion, loitering, running, object removal) → **Incident Agent** (autonomous correlation,
risk scoring, escalation) → **Sentinel Analyst** (LLM tool-calling agent: Q&A + shift reports).

## Run locally
```bash
python -m venv venv
venv\Scripts\activate            # Windows  (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
set GEMINI_API_KEY=your_key      # optional — without it the agent runs in offline mode
streamlit run app.py
```

## Secrets / environment variables (Streamlit Cloud: App settings → Secrets)
| Name | Purpose |
|---|---|
| `GEMINI_API_KEY` or `GROQ_API_KEY` | LLM for the Sentinel Analyst agent (free tiers work) |
| `LLM_PROVIDER` | optional: `gemini` / `groq` to force one |
| `LLM_MODEL` | optional: override model name(s), comma-separated |
| `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO` | optional email escalation |

## Team
CO · Kanza · Fiza
