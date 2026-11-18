"""Runtime configuration for the ScoutMind backend.

Values are read from ``SCOUTMIND_*`` environment variables or ``backend/.env``. The defaults bind the API to
loopback only and store data under ``backend/data``; nothing here may reach a LAN or public interface by default.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    """Process-wide settings, overridable per deployment through environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="SCOUTMIND_",
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ScoutMind"
    version: str = "0.1.0"
    host: str = "127.0.0.1"
    port: int = 8000

    database_url: str = f"sqlite:///{(DEFAULT_DATA_DIR / 'scoutmind.db').as_posix()}"
    data_dir: Path = DEFAULT_DATA_DIR

    api_token: str | None = None
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000"

    # A real FMSuperScout dump is ~90-150 MB; the scan protocol itself is much smaller.
    max_import_bytes: int = 256 * 1024 * 1024
    min_similar_sample: int = 5
    similar_limit: int = 20

    agent_llm_enabled: bool = False
    agent_llm_base_url: str = "https://api.deepseek.com"
    agent_llm_model: str = "deepseek-chat"
    agent_llm_api_key: str | None = None

    @property
    def allowed_origins(self) -> list[str]:
        """CORS origins parsed from the comma separated setting."""
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def raw_import_dir(self) -> Path:
        """Directory holding the untouched scan payloads of every import."""
        return self.data_dir / "raw"

    def ensure_directories(self) -> None:
        """Create the writable data directories the backend needs."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_import_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
