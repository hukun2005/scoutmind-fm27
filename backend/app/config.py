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

    # 发布包用：指向已构建的前端 dist 目录，由后端同端口托管（不需要 Node 运行时）。
    frontend_dist: str | None = None

    api_token: str | None = None
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000"

    # A real FMSuperScout dump is ~90-150 MB; the scan protocol itself is much smaller.
    max_import_bytes: int = 256 * 1024 * 1024
    # Hard ceiling applied before any payload is read into memory (Content-Length and chunked reads).
    max_request_bytes: int = 256 * 1024 * 1024
    # multipart 上传：文件数、普通字段数、单字段字节数与读取块大小。
    max_upload_files: int = 1
    max_multipart_fields: int = 32
    max_multipart_field_bytes: int = 1024 * 1024
    upload_chunk_size: int = 1024 * 1024
    # 单块上传数据的最长等待时间：慢速/挂起的上传不能一直占用工作进程。
    max_upload_read_seconds: int = 120
    # 并发：导入写库与上传解析分别限流，避免 SQLite 锁表或内存峰值。
    max_import_concurrency: int = 2
    max_upload_concurrency: int = 2
    # V3.3.2-05.2：本地后台转会雷达扫描。有界线程池 + 数据库持久化任务，不引入外部队列。
    scan_workers: int = 2
    scan_batch_size: int = 500
    scan_task_timeout_seconds: int = 1800
    scan_max_attempts: int = 2
    # V3.3.2-08：导入完成后是否自动触发在线学习。测试环境关闭，生产默认开启。
    learning_auto_start: bool = True
    # 兼容旧名字（上一版配置），保留以免已有部署配置失效。
    max_multipart_files: int = 1
    # V3.2.7.3：旧客户端（不带 WriteContext）的写入开关。默认允许，但每次都会写审计事件；
    # 设为 false 后，所有导入必须携带身份 + 会话 + 当前代次，否则返回 409。
    write_safety_legacy_allowed: bool = True

    def model_post_init(self, __context: object) -> None:
        """启动即校验：限制必须是正数，请求上限不能小于导入上限，旧配置名要兼容。"""
        positive = {
            "max_import_bytes": self.max_import_bytes,
            "max_request_bytes": self.max_request_bytes,
            "max_upload_files": self.max_upload_files,
            "max_multipart_fields": self.max_multipart_fields,
            "max_multipart_field_bytes": self.max_multipart_field_bytes,
            "upload_chunk_size": self.upload_chunk_size,
            "max_upload_read_seconds": self.max_upload_read_seconds,
            "max_import_concurrency": self.max_import_concurrency,
            "max_upload_concurrency": self.max_upload_concurrency,
            "scan_workers": self.scan_workers,
            "scan_batch_size": self.scan_batch_size,
            "scan_task_timeout_seconds": self.scan_task_timeout_seconds,
            "scan_max_attempts": self.scan_max_attempts,
        }
        for name, value in positive.items():
            if int(value) <= 0:
                raise ValueError(f"{name} 必须是正整数，当前 {value!r}")
        if self.max_request_bytes < self.max_import_bytes:
            raise ValueError("max_request_bytes 不能小于 max_import_bytes")
        if self.upload_chunk_size > self.max_import_bytes:
            raise ValueError("upload_chunk_size 不能大于 max_import_bytes")
        # 旧名字与新名字不一致时，以旧名字为准（它来自已有部署配置）。
        if self.max_multipart_files != 1 and self.max_multipart_files != self.max_upload_files:
            self.max_upload_files = self.max_multipart_files
    min_similar_sample: int = 5
    similar_limit: int = 20

    agent_llm_enabled: bool = False
    agent_llm_base_url: str = "https://api.deepseek.com"
    agent_llm_model: str = "deepseek-chat"
    agent_llm_api_key: str | None = None
    # SM-046：超时、重试与成本估算（真实联调仍需要 API Key）。
    agent_llm_timeout_seconds: float = 30.0
    agent_llm_max_retries: int = 2
    agent_llm_input_price_per_mtok: float = 0.0
    agent_llm_output_price_per_mtok: float = 0.0

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
