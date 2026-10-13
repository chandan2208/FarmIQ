"""Runtime settings, read once from the environment (.env is loaded if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _split(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = "FarmIQ"
    version: str = "2.0.0"
    env: str = os.getenv("FARMIQ_ENV", "development")
    root: Path = ROOT
    data_dir: Path = ROOT / "app" / "data"
    model_dir: Path = ROOT / "app" / "models"
    web_dir: Path = ROOT / "web"
    cache_dir: Path = Path(os.getenv("FARMIQ_CACHE_DIR", str(ROOT / "data" / "cache")))
    upload_dir: Path = Path(os.getenv("FARMIQ_UPLOAD_DIR", str(ROOT / "data" / "uploads")))
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'farmiq.db').as_posix()}")
    allowed_origins: list[str] = field(default_factory=lambda: _split(os.getenv("ALLOWED_ORIGINS"), ["*"]))
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or None
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    # data.gov.in publishes this sample key for evaluation; set your own for production quotas.
    data_gov_api_key: str = os.getenv("DATA_GOV_API_KEY", "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b")
    agmarknet_resource: str = "9ef84268-d588-465a-a308-a864a43d0070"
    http_timeout_s: float = float(os.getenv("HTTP_TIMEOUT_S", "20"))
    vision_min_confidence: float = float(os.getenv("VISION_MIN_CONFIDENCE", "0.45"))

    @property
    def is_prod(self) -> bool:
        return self.env.lower() in {"production", "prod"}


settings = Settings()
settings.cache_dir.mkdir(parents=True, exist_ok=True)
settings.upload_dir.mkdir(parents=True, exist_ok=True)
