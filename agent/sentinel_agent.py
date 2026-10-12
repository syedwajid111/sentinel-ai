"""
Sentinel AI Agent — the security analyst you can talk to.

Loop (ReAct style):
    user question
      -> LLM decides which tool(s) to call      (reason)
      -> we run the tool on the real database    (act)
      -> result goes back to the LLM             (observe)
      -> repeat until it can answer (max N steps)

Every step is recorded in `AgentResult.steps` so the UI can show *how* the agent
reached its answer (useful for the viva).

If no API key is configured, or the LLM is down, an offline planner picks tools by
keyword and fills a template, so the demo never dies.
"""
import json
import re
import time
from dataclasses import dataclass, field
from typing import List

import config
from agent.llm_client import LLMClient, LLMUnavailable
from agent.tools import SurveillanceTools, TOOL_SCHEMAS
from utils.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = f"""You are Sentinel, the AI security analyst inside "{config.APP_TITLE}", a CCTV
surveillance system. A YOLOv8 + ByteTrack vision pipeline detects people and valuables, a rule engine
raises alerts (zone_intrusion, loitering, running, object_removed), and an autonomous incident agent links
alerts into higher-level incidents with a risk score.

Rules:
- ALWAYS use the tools to get facts. Never invent numbers, times, track ids or zones.
- If the data is empty, say so plainly and suggest running monitoring on a video first.
- Be concise and practical, like a senior security officer briefing a manager. Use short bullet points.
- When you mention an incident or alert, include its time and zone/track id.
- End with a clear recommended action when something risky was found.
- The system flags *patterns associated with* theft; it cannot prove a crime. Say "possible"/"probable".
- Reply in the same language the user writes in (English or Roman Urdu).
"""


@dataclass
class AgentStep:
    tool: str
    arguments: dict
    result_preview: str


@dataclass
class AgentResult:
    answer: str
    steps: List[AgentStep] = field(default_factory=list)
    mode: str = "llm"          # "llm" | "offline"
    note: str = ""


class SentinelAgent:
    def __init__(self, db, max_steps=None):
        self.db = db
        self.tools = SurveillanceTools(db)
        self.llm = LLMClient()
        self.max_steps = max_steps or config.AGENT_MAX_STEPS

    # =============================================================== chat
    def ask(self, question, history=None) -> AgentResult:
        if self.llm.available:
            try:
                return self._ask_llm(question, history or [])
            except LLMUnavailable as exc:
                logger.warning("LLM unavailable, using offline agent: %s", exc)
                res = self._ask_offline(question)
                res.note = "LLM unavailable right now, answered by the offline planner."
                return res
        return self._ask_offline(question)

    def _ask_llm(self, question, history):
        now = time.strftime("%Y-%m-%d %H:%M", time.localtime())
        messages = [{"role": "system", "content": SYSTEM_PROMPT + f"\nCurrent local time: {now}."}]
        for turn in history[-6:]:  # short memory of the conversation
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": question})

        steps = []
        for _ in range(self.max_steps):
            msg = self.llm.chat(messages, tools=TOOL_SCHEMAS)
            calls = msg.get("tool_calls") or []
            if not calls:
                return AgentResult(answer=(msg.get("content") or "").strip() or "(no answer)", steps=steps)

            messages.append(msg)  # echo back exactly (keeps provider-specific fields)
            for call in calls:
                name = call["function"]["name"]
                raw_args = call["function"].get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}
                result = self.tools.execute(name, args)
                result_json = json.dumps(result, default=str)
                steps.append(AgentStep(name, args, result_json[:400]))
                messages.append({"role": "tool", "tool_call_id": call.get("id", name),
                                 "name": name, "content": result_json[:12000]})

        messages.append({"role": "user", "content": "Give your final answer now using the data above."})
        msg = self.llm.chat(messages)
        return AgentResult(answer=(msg.get("content") or "").strip(), steps=steps)

    # =============================================================== offline planner
    def _ask_offline(self, question) -> AgentResult:
        q = question.lower()
        hours = _extract_hours(q)
        steps = []

        def call(name, **args):
            res = self.tools.execute(name, args)
            steps.append(AgentStep(name, args, json.dumps(res, default=str)[:400]))
            return res

        track = re.search(r"(?:#|id\s*|track\s*|person\s*)(\d+)", q)
        if track and any(w in q for w in ("person", "track", "#", "id")):
            res = call("get_track_timeline", track_id=int(track.group(1)))
            if not res.get("count"):
                text = f"No alerts recorded for track #{track.group(1)}."
            else:
                lines = [f"- {e['time']} · **{e['type']}** ({e['severity']}) — {e['message']}" for e in res["timeline"]]
                text = f"**Timeline for track #{track.group(1)}** ({res['count']} alerts):\n" + "\n".join(lines)
            return AgentResult(text, steps, mode="offline")

        if any(w in q for w in ("how does", "how do", "kaise kaam", "configuration", "threshold", "model")):
            cfg = call("get_system_configuration")
            text = "**How Sentinel works**\n" + "\n".join(f"- {k.replace('_', ' ')}: {v}" for k, v in cfg.items())
            return AgentResult(text, steps, mode="offline")

        if any(w in q for w in ("zone", "area", "hotspot", "risky", "dangerous")):
            rank = call("get_zone_risk_ranking", hours=hours)["ranking"]
            if not rank:
                return AgentResult(_EMPTY, steps, mode="offline")
            lines = [f"{i+1}. **{r['zone']}** — {r['risk_points']} risk points ({r['events']} alerts)"
                     for i, r in enumerate(rank[:5])]
            return AgentResult(f"**Zone risk ranking (last {hours:g}h)**\n" + "\n".join(lines), steps, mode="offline")

        if any(w in q for w in ("theft", "chori", "incident", "steal", "stolen", "suspicious", "danger")):
            inc = call("get_incidents", hours=hours)
            if not inc["count"]:
                return AgentResult(f"No incidents were raised in the last {hours:g}h. "
                                   "Individual alerts may still exist — ask for a summary.", steps, mode="offline")
            lines = [f"- **{i['time']}** · risk **{i['risk_score']}** · {i['title']}\n  - Why: {i['reasoning']}\n"
                     f"  - Action: {i['action_taken']}" for i in inc["incidents"][:6]]
            return AgentResult(f"**{inc['count']} incident(s) in the last {hours:g}h**\n" + "\n".join(lines),
                               steps, mode="offline")

        for rule, words in {"running": ("run", "bhag", "bhaag", "flee", "fast"), "loitering": ("loiter",),
                            "object_removed": ("removed", "missing", "bag", "laptop", "phone"),
                            "zone_intrusion": ("intrusion", "entered", "enter")}.items():
            if any(w in q for w in words):
                res = call("search_events", event_type=rule, hours=hours, limit=10)
                if not res["count"]:
                    return AgentResult(f"No **{rule.replace('_', ' ')}** alerts in the last {hours:g}h.", steps,
                                       mode="offline")
                lines = [f"- {e['time']} · {e['message']}" for e in res["events"]]
                return AgentResult(f"**{res['count']} {rule.replace('_', ' ')} alert(s), last {hours:g}h**\n"
                                   + "\n".join(lines), steps, mode="offline")

        # default: overview
        ov = call("get_security_overview", hours=hours)
        if not ov["total_events"]:
            return AgentResult(_EMPTY, steps, mode="offline")
        inc = call("get_incidents", hours=hours, min_risk=70)
        text = _overview_text(ov, inc)
        return AgentResult(text, steps, mode="offline")

    # =============================================================== report
    def generate_report(self, hours=24) -> AgentResult:
        """Security shift report: hard numbers from tools + (if available) LLM-written analysis."""
        steps = []

        def call(name, **args):
            res = self.tools.execute(name, args)
            steps.append(AgentStep(name, args, json.dumps(res, default=str)[:400]))
            return res

        ov = call("get_security_overview", hours=hours)
        inc = call("get_incidents", hours=hours)
        zones = call("get_zone_risk_ranking", hours=hours)
        crit = call("search_events", severity="critical", hours=hours, limit=15)

        analysis, mode, note = None, "offline", ""
        if self.llm.available and ov["total_events"]:
            try:
                data = json.dumps({"overview": ov, "incidents": inc, "zone_ranking": zones,
                                   "critical_alerts": crit}, default=str)[:14000]
                msg = self.llm.chat([
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content":
                        "Write the analysis part of a security shift report from this data. Sections (markdown "
                        "### headings): Executive summary (3 lines), Key incidents, Patterns & hotspots, "
                        "Recommendations (3-5 concrete actions for the security team). Do not repeat raw tables. "
                        f"English only.\n\nDATA:\n{data}"},
                ], temperature=0.3)
                analysis, mode = (msg.get("content") or "").strip(), "llm"
            except LLMUnavailable as exc:
                note = f"LLM unavailable ({exc.__class__.__name__}); rule-based analysis used."

        if not analysis:
            analysis = _rule_based_analysis(ov, inc, zones)

        report = _render_report(hours, ov, inc, zones, crit, analysis, self.llm.describe() if mode == "llm"
                                else "offline rule-based")
        return AgentResult(report, steps, mode=mode, note=note)


# ---------------------------------------------------------------------- helpers
_EMPTY = ("No alerts are recorded yet. Run **Live monitor** on a video (or load demo data on the "
          "AI Agent page) and then ask me again.")


def _extract_hours(q):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(hour|hr|h\b|ghant)", q)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*(day|din)", q)
    if m:
        return float(m.group(1)) * 24
    if "week" in q or "hafta" in q:
        return 168
    return 24


def _overview_text(ov, inc):
    types = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in ov["events_by_type"].items())
    sev = ov["events_by_severity"]
    lines = [
        f"**Security overview — last {ov['period_hours']:g}h**",
        f"- Total alerts: **{ov['total_events']}** ({types})",
        f"- Critical: {sev.get('critical', 0)} · Warning: {sev.get('warning', 0)} · Info: {sev.get('info', 0)}",
        f"- Busiest hour: {ov['busiest_hour']}",
        f"- Incidents raised by the incident agent: **{ov['incidents_raised']}** "
        f"(highest risk {ov['highest_incident_risk']}/100)",
    ]
    if inc and inc["count"]:
        lines.append("\n**High-risk incidents:**")
        lines += [f"- {i['time']} · risk {i['risk_score']} · {i['title']}" for i in inc["incidents"][:5]]
        lines.append("\n**Recommended action:** review the snapshots of these incidents in the Alerts log.")
    return "\n".join(lines)


def _rule_based_analysis(ov, inc, zones):
    if not ov["total_events"]:
        return "### Executive summary\nNo activity was recorded in this period."
    top_zone = zones["ranking"][0]["zone"] if zones["ranking"] else "n/a"
    crit = ov["events_by_severity"].get("critical", 0)
    level = "HIGH" if ov["highest_incident_risk"] >= 75 else "MEDIUM" if ov["highest_incident_risk"] >= 45 else "LOW"
    recs = []
    if ov["events_by_type"].get("loitering"):
        recs.append(f"Increase guard patrols around **{top_zone}**, where loitering keeps recurring.")
    if ov["events_by_type"].get("object_removed"):
        recs.append("Check the snapshots of every *object removed* alert and verify with the owner of the item.")
    if ov["events_by_type"].get("running"):
        recs.append("Review footage just before each *running* alert to see what triggered it.")
    if inc["count"]:
        recs.append("Escalate critical incidents to the site manager and keep the footage as evidence.")
    recs.append("Re-check camera angles / zone boundaries if alerts look like false positives.")
    return "\n".join([
        "### Executive summary",
        f"Overall threat level: **{level}**. {ov['total_events']} alerts ({crit} critical) and "
        f"{inc['count']} correlated incident(s). Highest-risk area: **{top_zone}**.",
        "### Recommendations",
        *[f"- {r}" for r in recs],
    ])


def _render_report(hours, ov, inc, zones, crit, analysis, engine):
    now = time.strftime("%Y-%m-%d %H:%M", time.localtime())
    out = [
        f"# Security Shift Report",
        f"**System:** {config.APP_TITLE}  \n**Period:** last {hours:g} hours  \n**Generated:** {now}  \n"
        f"**Analysis by:** Sentinel AI Agent ({engine})",
        "",
        analysis,
        "",
        "## Numbers",
        f"| Metric | Value |\n|---|---|\n| Total alerts | {ov['total_events']} |\n"
        f"| Critical | {ov['events_by_severity'].get('critical', 0)} |\n"
        f"| Warning | {ov['events_by_severity'].get('warning', 0)} |\n"
        f"| Incidents | {ov['incidents_raised']} |\n| Highest risk | {ov['highest_incident_risk']}/100 |\n"
        f"| Busiest hour | {ov['busiest_hour'] or '—'} |",
    ]
    if inc["count"]:
        out += ["", "## Incidents", "| Time | Risk | Incident | Action |", "|---|---|---|---|"]
        out += [f"| {i['time']} | {i['risk_score']} | {i['title']} | {i['action_taken']} |"
                for i in inc["incidents"]]
    if zones["ranking"]:
        out += ["", "## Zone risk ranking", "| Zone | Risk points | Alerts |", "|---|---|---|"]
        out += [f"| {z['zone']} | {z['risk_points']} | {z['events']} |" for z in zones["ranking"]]
    if crit["count"]:
        out += ["", "## Critical alerts", *[f"- {e['time']} — {e['message']}" for e in crit["events"]]]
    out += ["", "---", "_Sentinel flags behaviour patterns associated with theft or intrusion. "
                       "Every alert should be verified by a human before action is taken._"]
    return "\n".join(out)
