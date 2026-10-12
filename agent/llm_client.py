"""
Minimal LLM client for any OpenAI-compatible chat-completions API with tool calling.

Works with (set any or all — they are tried in this order, falling through on failure):
  * Google Gemini   (free tier)  -> GEMINI_API_KEY   (old "AIza..." and new "AQ." keys)
  * Groq            (free tier)  -> GROQ_API_KEY
  * Any OpenAI-compatible server  -> LLM_API_KEY + LLM_BASE_URL + LLM_MODEL

Plain `requests` is used on purpose (no vendor SDK), so switching provider is just
an environment variable and nothing breaks when an SDK changes.
"""
import os

import requests

PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        # tried in order; if one is unavailable/rate-limited the next is used
        "models": ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"],
        # Google keys work with x-goog-api-key; new "AQ." keys can be rejected as Bearer tokens
        "auth_styles": ["goog", "bearer", "query"],
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        "auth_styles": ["bearer"],
    },
    "custom": {
        "base_url": os.getenv("LLM_BASE_URL", ""),
        "key_env": "LLM_API_KEY",
        "models": [m.strip() for m in os.getenv("LLM_MODEL", "").split(",") if m.strip()],
        "auth_styles": ["bearer"],
    },
}


class LLMUnavailable(Exception):
    pass


class LLMClient:
    def __init__(self):
        self.backends = self._detect()
        self.active = None  # (provider, model) that last answered
        self._auth_ok = {}  # provider -> auth style that worked

    @staticmethod
    def _detect():
        preferred = os.getenv("LLM_PROVIDER", "").lower()
        order = [preferred] if preferred in PROVIDERS else []
        order += [p for p in ("gemini", "groq", "custom") if p not in order]
        override = [m.strip() for m in os.getenv("LLM_MODEL", "").split(",") if m.strip()]
        out = []
        for name in order:
            cfg = PROVIDERS[name]
            key = os.getenv(cfg["key_env"], "").strip()
            if not (key and cfg["base_url"] and cfg["models"]):
                continue
            models = override if (override and name == (preferred or name) and name != "custom") else cfg["models"]
            out.append({"name": name, "cfg": cfg, "key": key, "models": models})
        return out

    @property
    def available(self):
        return bool(self.backends)

    def describe(self):
        if not self.available:
            return "offline mode (no API key set)"
        if self.active:
            return f"{self.active[0]} · {self.active[1]}"
        return " → ".join(b["name"] for b in self.backends) + " (ready)"

    def _request(self, backend, style, payload, timeout):
        url = f"{backend['cfg']['base_url'].rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        params = None
        if style == "goog":
            headers["x-goog-api-key"] = backend["key"]
        elif style == "query":
            params = {"key": backend["key"]}
        else:
            headers["Authorization"] = f"Bearer {backend['key']}"
        return requests.post(url, headers=headers, params=params, json=payload, timeout=timeout)

    def chat(self, messages, tools=None, temperature=0.2, timeout=45):
        if not self.available:
            raise LLMUnavailable("No LLM API key configured")
        errors = []
        for backend in self.backends:
            name = backend["name"]
            styles = [self._auth_ok[name]] if name in self._auth_ok else backend["cfg"]["auth_styles"]
            for model in backend["models"]:
                payload = {"model": model, "messages": messages, "temperature": temperature}
                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"
                auth_failed = True
                for style in styles:
                    try:
                        r = self._request(backend, style, payload, timeout)
                    except requests.RequestException as exc:
                        errors.append(f"{name}/{model}: {exc}")
                        auth_failed = False
                        break
                    if r.status_code == 200:
                        self._auth_ok[name] = style
                        self.active = (name, model)
                        return r.json()["choices"][0]["message"]
                    errors.append(f"{name}/{model} [{style}]: HTTP {r.status_code} {r.text[:160]}")
                    if r.status_code not in (400, 401, 403):  # not an auth problem -> next model
                        auth_failed = False
                        break
                if auth_failed and len(styles) and r.status_code in (401, 403):
                    break  # key rejected in every style: other models won't help, try next provider
        raise LLMUnavailable("; ".join(errors[-6:]) or "LLM request failed")
