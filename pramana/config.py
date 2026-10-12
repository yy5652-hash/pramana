"""Settings, read once from the environment (and a local `.env`, if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal `.env` reader: KEY=VALUE lines, no interpolation. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _models(name: str, default: str) -> list[str]:
    return [m.strip() for m in os.environ.get(name, default).split(",") if m.strip()]


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.environ.get("PRAMANA_DATA", ROOT / "data"))
    course_dir: Path = ROOT / "course"

    # Any OpenAI-compatible chat endpoint works (Gemini, OpenAI, Ollama, Groq, vLLM, ...).
    llm_base_url: str = os.environ.get(
        "LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    llm_api_key: str = os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY", "")

    # Each role takes a comma-separated chain in order of preference. A request moves down
    # the chain when a model is rate-limited or out of quota, which is what makes a
    # free-tier key usable. The defaults fit Gemini's free tier, where the larger "flash"
    # models allow only a few dozen requests a day: they are kept for the two jobs where
    # quality matters most and volume is low (the concept map, writing questions), and the
    # fast "flash-lite" model does everything else.
    author_models: list[str] = field(
        default_factory=lambda: _models("PRAMANA_AUTHOR_MODELS", "gemini-3.6-flash,gemini-3.5-flash,gemini-3.8-flash,gemini-3.5-flash-lite")
    )
    tutor_models: list[str] = field(
        default_factory=lambda: _models("PRAMANA_TUTOR_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite")
    )
    # Checks questions blind. Must differ from the model that wrote them (enforced in code).
    verifier_models: list[str] = field(
        default_factory=lambda: _models("PRAMANA_VERIFIER_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.5-flash")
    )
    # The evaluation's judge is deliberately not the model that writes the tutor's answers:
    # a model marking its own work agrees with itself.
    judge_models: list[str] = field(
        default_factory=lambda: _models("PRAMANA_JUDGE_MODELS", "gemini-3.1-flash-lite,gemini-3.5-flash")
    )
    vision_models: list[str] = field(
        default_factory=lambda: _models("PRAMANA_VISION_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite")
    )
    bulk_models: list[str] = field(
        default_factory=lambda: _models("PRAMANA_BULK_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite")
    )
    requests_per_minute: int = int(os.environ.get("PRAMANA_RPM", "12"))

    # replay: never call the network, answer only from the response cache (deterministic re-runs).
    # live:   call the endpoint, write every response to the cache.
    llm_mode: str = os.environ.get("PRAMANA_LLM_MODE", "live")

    embed_model: str = os.environ.get("PRAMANA_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    rerank_model: str = os.environ.get("PRAMANA_RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
    whisper_model: str = os.environ.get("PRAMANA_WHISPER_MODEL", "small.en")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "llm_cache"

    def course_db(self, course_id: str) -> Path:
        return self.data_dir / "kb" / course_id / "kb.sqlite"

    def asset_dir(self, course_id: str) -> Path:
        return self.data_dir / "kb" / course_id / "assets"


settings = Settings()
