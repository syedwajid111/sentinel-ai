"""
Handles what happens when a behavior rule fires: save a snapshot, write the
event to the database, and (optionally) sound/email notification.
"""
import os
import time
import smtplib
from email.message import EmailMessage

import cv2

import config
from database.db_manager import DBManager
from agent.incident_agent import IncidentAgent
from utils.logger import get_logger

logger = get_logger(__name__)


class AlertManager:
    def __init__(self):
        self.db = DBManager(config.DB_PATH)
        self.incident_agent = IncidentAgent(self.db, notifier=self._notify_incident)
        self.new_incidents = []   # read (and cleared) by the video processor for the live UI

    def handle(self, alert, frame):
        snapshot_path = self._save_snapshot(alert, frame)
        self.db.insert_event_returning_id(
            track_id=alert.track_id,
            rule=alert.rule,
            zone=alert.zone,
            message=alert.message,
            severity=alert.severity,
            timestamp=alert.timestamp,
            snapshot_path=snapshot_path,
        )
        logger.info("ALERT [%s] %s", alert.severity.upper(), alert.message)

        # Autonomous step: the incident agent re-reads the recent event stream and
        # decides whether this alert completes a bigger threat pattern.
        try:
            self.new_incidents.extend(self.incident_agent.observe())
        except Exception as exc:
            logger.warning("Incident agent failed: %s", exc)

        if config.ENABLE_SOUND_ALERTS:
            self._beep()
        if config.ENABLE_EMAIL_ALERTS and alert.severity == "critical":
            self._send_email(alert, snapshot_path)

    def _save_snapshot(self, alert, frame):
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{alert.rule}_id{alert.track_id}.jpg"
        path = os.path.join(config.SNAPSHOTS_DIR, filename)
        try:
            cv2.imwrite(path, frame)
        except Exception as exc:
            logger.warning("Failed to save snapshot: %s", exc)
            return ""
        return path

    def _beep(self):
        try:
            print("\a", end="", flush=True)  # cross-platform terminal bell
        except Exception:
            pass

    def _notify_incident(self, incident):
        if not config.ENABLE_EMAIL_ALERTS:
            return False
        try:
            msg = EmailMessage()
            msg["Subject"] = f"[Sentinel AI] {incident.title} (risk {incident.risk_score})"
            msg["From"] = config.SMTP_USERNAME
            msg["To"] = config.ALERT_EMAIL_TO
            msg.set_content(f"{incident.title}\n\nRisk: {incident.risk_score}/100\nZone: {incident.zone or '-'}\n\n"
                            f"Why: {incident.reasoning}")
            with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
                server.send_message(msg)
            return True
        except Exception as exc:
            logger.warning("Failed to send incident email: %s", exc)
            return False

    def _send_email(self, alert, snapshot_path):
        if not (config.SMTP_SERVER and config.ALERT_EMAIL_TO):
            return
        try:
            msg = EmailMessage()
            msg["Subject"] = f"[Surveillance Alert] {alert.rule} - {alert.severity}"
            msg["From"] = config.SMTP_USERNAME
            msg["To"] = config.ALERT_EMAIL_TO
            msg.set_content(alert.message)
            if snapshot_path and os.path.isfile(snapshot_path):
                with open(snapshot_path, "rb") as f:
                    msg.add_attachment(f.read(), maintype="image", subtype="jpeg",
                                        filename=os.path.basename(snapshot_path))
            with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
                server.starttls()
                server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
                server.send_message(msg)
        except Exception as exc:
            logger.warning("Failed to send email alert: %s", exc)
