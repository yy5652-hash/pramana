"""One small client for any OpenAI-compatible chat endpoint.

Three things matter for this project and are handled here rather than at call sites:

* **Replayable cache.** Every response is appended to `data/llm_cache/<namespace>.jsonl`,
  keyed by a hash of the request. With `PRAMANA_LLM_MODE=replay` nothing touches the
  network, so ingestion, the question bank and the whole evaluation re-run bit-for-bit
  without an API key.
* **Fallback chain.** A call names a list of models. A rate-limited or overloaded model is
  put on cool-down and the next one is tried, so a free-tier key can still do bulk work.
* **Structured output.** Pass a JSON schema and get a parsed object back.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import settings


class ReplayMiss(RuntimeError):
    """Raised in replay mode when a request is not in the cache."""


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    cached: bool
    usage: dict[str, int]

    def json(self) -> Any:
        return repair_latex(parse_json(self.text))


def parse_json(text: str) -> Any:
    """Parse a model reply that should be JSON, tolerating code fences and stray prose."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        end = max(text.rfind("}"), text.rfind("]"))
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


_MATH = re.compile(r"\$\$.*?\$\$|\$[^$]*\$", re.S)
_DOUBLED = re.compile(r"(?<!\\)\\\\(?=[A-Za-z])")
_SPELLED_NEWLINE = re.compile(r"\\n(?=\s*(?:[•\-–*]|\d+[.)]|\\n|$))|(?<=\\n)\\n(?=[A-Z])")
_EATEN = {"\t": "\\t", "\r": "\\r", "\n": "\\n"}
_EATEN_COMMAND = re.compile(
    r"[\t\r\n](?=(?:ext|extbf|extit|extrm|extstyle|heta|imes|au|an|o|ilde|riangle|frac|ightarrow|ho|angle|eq|u|abla|e|ot|eg)(?![a-z]))")


def repair_latex(value: Any) -> Any:
    """Undo the two ways a model's JSON mangles LaTeX, in every string of a parsed reply.

    A backslash in JSON must be written twice. Models get this wrong in both directions:
    `\\frac` typed with one backslash is read by the JSON parser as a form feed followed by
    "rac" (likewise `\\text` -> tab, `\\bar` -> backspace, `\\nu` -> newline), and an
    over-careful model sends four, which leaves `\\\\Delta` and renders as a line break
    followed by the word "Delta". Form feeds and backspaces never belong in course text, so
    they are restored everywhere; tabs, returns and newlines only inside maths and only
    where they complete a LaTeX command.
    """
    if isinstance(value, dict):
        return {key: repair_latex(item) for key, item in value.items()}
    if isinstance(value, list):
        return [repair_latex(item) for item in value]
    if not isinstance(value, str):
        return value
    text = value.replace("\x0c", "\\f").replace("\x08", "\\b").replace("\x0b", "\\v")
    text = _DOUBLED.sub(r"\\", text)
    pieces, cursor = [], 0
    for match in _MATH.finditer(text):
        # Outside maths, a spelled-out "\\n" before a bullet or a new line of a list is a line break.
        pieces.append(_SPELLED_NEWLINE.sub("\n", text[cursor:match.start()]))
        pieces.append(_EATEN_COMMAND.sub(lambda c: _EATEN[c.group(0)], match.group(0)))
        cursor = match.end()
    pieces.append(_SPELLED_NEWLINE.sub("\n", text[cursor:]))
    return "".join(pieces)


def repair_maths(text: str) -> str:
    """The same repair for a string that is maths throughout, such as an equation block,
    which arrives without `$` around it."""
    text = _DOUBLED.sub(r"\\", text.replace("\x0c", "\\f").replace("\x08", "\\b").replace("\x0b", "\\v"))
    return _EATEN_COMMAND.sub(lambda c: _EATEN[c.group(0)], text)


def image_part(path: str | Path) -> dict:
    """A chat content part carrying a local image."""
    data = Path(path).read_bytes()
    mime = "image/png" if str(path).lower().endswith(".png") else "image/jpeg"
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"},
    }


def _request_key(messages: list[dict], schema: dict | None, temperature: float, salt: str) -> str:
    blob = json.dumps(
        {"messages": messages, "schema": schema, "temperature": temperature, "salt": salt},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


class _Cache:
    """Append-only JSONL files, one per namespace, loaded lazily."""

    def __init__(self, directory: Path):
        self.directory = directory
        self._data: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    def _load(self, namespace: str) -> dict[str, dict]:
        if namespace not in self._data:
            entries: dict[str, dict] = {}
            path = self.directory / f"{namespace}.jsonl"
            if path.exists():
                for line in path.read_text().splitlines():
                    if line.strip():
                        row = json.loads(line)
                        entries[row["key"]] = row
            self._data[namespace] = entries
        return self._data[namespace]

    def get(self, namespace: str, key: str) -> dict | None:
        with self._lock:
            return self._load(namespace).get(key)

    def put(self, namespace: str, key: str, row: dict) -> None:
        with self._lock:
            self._load(namespace)[key] = row
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / f"{namespace}.jsonl").open("a") as handle:
                handle.write(json.dumps({"key": key, **row}, ensure_ascii=False) + "\n")


class _Limiter:
    """Paces requests per model and keeps a model out of rotation after an error reply.

    Two clocks per model: `_paced` spaces ordinary requests (requests per minute), and
    `_resting` holds a model back after a 429 or 5xx for as long as the server asked. The
    chain is a preference order, so the pick is the first model that is not resting; pacing
    alone never pushes a request down the chain.
    """

    def __init__(self, requests_per_minute: int):
        self.interval = 60.0 / max(requests_per_minute, 1)
        self._paced: dict[str, float] = {}
        self._resting: dict[str, float] = {}
        self._lock = threading.Lock()

    def reserve(self, models: list[str]) -> tuple[str, float]:
        """Pick a model and return it with the wait in seconds."""
        with self._lock:
            now = time.monotonic()
            rest = {m: max(self._resting.get(m, 0.0) - now, 0.0) for m in models}
            model = next((m for m in models if rest[m] == 0.0), min(models, key=rest.get))
            ready = max(self._paced.get(model, 0.0), now + rest[model], now)
            self._paced[model] = ready + self.interval
            return model, ready - now

    def exhausted(self, models: list[str]) -> bool:
        """True when every model in the chain is resting for longer than a request should wait."""
        with self._lock:
            now = time.monotonic()
            return all(self._resting.get(m, 0.0) - now > 300 for m in models)

    def cool_down(self, model: str, seconds: float) -> None:
        with self._lock:
            self._resting[model] = max(self._resting.get(model, 0.0), time.monotonic() + seconds)


class LLM:
    def __init__(self) -> None:
        self.cache = _Cache(settings.cache_dir)
        self.limiter = _Limiter(settings.requests_per_minute)
        self._client = httpx.Client(timeout=180)
        self.calls = 0
        self.cache_hits = 0

    def chat(
        self,
        messages: list[dict],
        *,
        models: list[str],
        namespace: str,
        schema: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        salt: str = "",
        cache_key: list | None = None,
        use_cache: bool = True,
        max_attempts: int = 8,
    ) -> LLMResult:
        """Send a chat request.

        `salt` separates otherwise identical requests (e.g. resampling). `cache_key` replaces
        the request hash with a stable identity, for requests that embed rendered images.
        """
        if cache_key is not None:
            key = hashlib.sha256(json.dumps(cache_key, sort_keys=True).encode()).hexdigest()
        else:
            key = _request_key(messages, schema, temperature, salt)
        if use_cache:
            _trace(namespace, key)
            hit = self.cache.get(namespace, key)
            if hit:
                self.cache_hits += 1
                return LLMResult(hit["text"], hit["model"], True, hit.get("usage", {}))
        if settings.llm_mode == "replay":
            raise ReplayMiss(f"no cached response in '{namespace}' for request {key[:12]}")
        if not settings.llm_api_key:
            raise LLMError("no API key. A question of your own needs a model: put a free Gemini key "
                           "(https://aistudio.google.com/apikey) in .env as LLM_API_KEY and restart the app. "
                           "The suggested questions, practice and a new student's lessons work without one.")

        last_error = "no attempt made"
        for attempt in range(max_attempts):
            if self.limiter.exhausted(models):
                raise LLMError(f"every model in the chain is out of quota ({', '.join(models)}); last error: {last_error}")
            model, wait = self.limiter.reserve(models)
            if wait > 0:
                time.sleep(wait)
            body: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
            if max_tokens:
                body["max_tokens"] = max_tokens
            if schema is not None:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "reply", "schema": schema},
                }
            try:
                response = self._client.post(
                    f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                    json=body,
                )
            except httpx.HTTPError as error:
                last_error = f"{model}: {type(error).__name__}"
                self.limiter.cool_down(model, 5 + 5 * attempt)
                continue
            if response.status_code in (429, 500, 502, 503, 504):
                delay = _retry_delay(response, attempt)
                last_error = f"{model}: HTTP {response.status_code}"
                _debug(f"{namespace}: {last_error}, resting it {delay:.0f}s")
                self.limiter.cool_down(model, delay)
                continue
            if response.status_code == 404 and len(models) > 1:
                # A retired or unknown model name: skip it for the rest of this process.
                last_error = f"{model}: HTTP 404 (model not available)"
                self.limiter.cool_down(model, 86400)
                continue
            if response.status_code != 200:
                raise LLMError(f"{model}: HTTP {response.status_code} {response.text[:300]}")
            payload = response.json()
            choice = payload["choices"][0]
            text = choice["message"].get("content") or ""
            if not text.strip():
                last_error = f"{model}: empty reply ({choice.get('finish_reason')})"
                continue
            if schema is not None:
                try:
                    parse_json(text)
                except json.JSONDecodeError:
                    last_error = f"{model}: reply was not valid JSON"
                    continue
            usage = {k: v for k, v in (payload.get("usage") or {}).items() if isinstance(v, int)}
            _debug(f"{namespace}: {model} ok in {response.elapsed.total_seconds():.1f}s")
            self.calls += 1
            if use_cache:
                self.cache.put(namespace, key, {"model": model, "text": text, "usage": usage})
            return LLMResult(text, model, False, usage)
        raise LLMError(f"gave up after {max_attempts} attempts; last error: {last_error}")


def _trace(namespace: str, key: str) -> None:
    """With PRAMANA_CACHE_TRACE=<file>, record every cache key a run asks for. `scripts/prune_cache.py`
    uses the record to drop replies that no current code path requests any more."""
    path = os.environ.get("PRAMANA_CACHE_TRACE")
    if path:
        with _trace_lock, open(path, "a") as handle:
            handle.write(f"{namespace}\t{key}\n")


_trace_lock = threading.Lock()


def _debug(message: str) -> None:
    """Per-call trace on stderr when PRAMANA_LLM_DEBUG is set."""
    if os.environ.get("PRAMANA_LLM_DEBUG"):
        print(f"[llm {time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Seconds to keep a model out of rotation after an error reply.

    A per-minute limit asks for a short wait and gets it. A per-day limit asks for hours;
    the model is then parked for that whole time and the chain moves on.
    """
    match = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', response.text)
    if match:
        return float(match.group(1)) + 1.0
    if response.status_code == 429:
        return min(20.0 * (attempt + 1), 90.0)
    return 20.0   # overloaded or failing: step aside for a while and let the next model answer


_default: LLM | None = None


def llm() -> LLM:
    global _default
    if _default is None:
        _default = LLM()
    return _default
