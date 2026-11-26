"""ScoutMind FM27 桌面版入口。

把 FastAPI 后端、Alembic 迁移和前端生产构建打进一个可执行程序：双击后在本机启动服务，
用一个原生窗口（WebView2）打开界面，数据保存在可执行文件旁的 data 目录。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_TITLE = "ScoutMind FM27"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """PyInstaller 解包目录（开发时是仓库根目录）。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def app_root() -> Path:
    """可执行文件所在目录（开发时是仓库根目录）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return resource_root()


def setup_logging(base: Path) -> logging.Logger:
    log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_dir / "desktop.log", encoding="utf-8")],
        force=True,
    )
    return logging.getLogger("scoutmind.desktop")


def redirect_streams(base: Path) -> None:
    """窗口程序没有控制台；把 stdout/stderr 接到文件，异常与原生崩溃信息才不会丢失。"""
    if not is_frozen():
        return
    log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stream = open(log_dir / "desktop.stderr.log", "a", buffering=1, encoding="utf-8")  # noqa: SIM115
    sys.stdout = stream
    sys.stderr = stream


def configure_environment(base: Path, resources: Path) -> None:
    data_dir = base / "data"
    (data_dir / "raw").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SCOUTMIND_DATA_DIR", str(data_dir))
    os.environ.setdefault(
        "SCOUTMIND_DATABASE_URL", f"sqlite:///{(data_dir / 'scoutmind.db').as_posix()}"
    )
    os.environ.setdefault("SCOUTMIND_FRONTEND_DIST", str(resources / "frontend" / "dist"))
    os.environ.setdefault("SCOUTMIND_HOST", "127.0.0.1")
    if not is_frozen():
        sys.path.insert(0, str(resources / "backend"))


def upgrade_database(resources: Path, logger: logging.Logger) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(resources / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(resources / "backend" / "alembic"))
    logger.info("执行数据库迁移")
    command.upgrade(config, "head")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_healthy(port: int, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/v1/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


class Backend:
    def __init__(self, port: int, logger: logging.Logger) -> None:
        self.port = port
        self.logger = logger
        self.server = None

    def start(self) -> None:
        import uvicorn

        from app.main import app

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        thread = threading.Thread(target=self.server.run, name="scoutmind-api", daemon=True)
        thread.start()
        if not wait_until_healthy(self.port):
            raise RuntimeError("后端未能在 90 秒内就绪，请查看 logs/desktop.log")

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
            time.sleep(1.0)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def read_instance(base: Path) -> dict | None:
    marker = base / "data" / "instance.json"
    if not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    port = payload.get("port")
    if not isinstance(port, int):
        return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=1.5) as response:
            if response.status == 200:
                return payload
    except (urllib.error.URLError, OSError):
        return None
    return None


def write_instance(base: Path, port: int) -> None:
    marker = base / "data" / "instance.json"
    marker.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")


def open_window(url: str, logger: logging.Logger) -> None:
    import webview

    window = webview.create_window(
        APP_TITLE,
        url,
        width=1480,
        height=920,
        min_size=(1100, 700),
        text_select=True,
    )
    logger.info("打开桌面窗口 %s", url)
    webview.start()
    window.destroy()


def show_error(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, 0x10)
    except Exception:  # noqa: BLE001 - 最后的兜底提示不应再次抛错
        print(message, file=sys.stderr)


def watch_parent(stdin, backend: "Backend", logger: logging.Logger) -> None:
    """Electron 退出时会关闭 stdin 管道，这里据此结束本地服务，避免残留子进程。"""
    try:
        stdin.buffer.read()
    except Exception:  # noqa: BLE001 - 管道异常按父进程已退出处理
        pass
    logger.info("父进程管道已关闭，停止本地服务")
    try:
        backend.stop()
    finally:
        os._exit(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--headless", action="store_true", help="只启动后端，不打开窗口（用于自动验收）")
    parser.add_argument("--port", type=int, default=0, help="固定端口；默认自动选择空闲端口")
    parser.add_argument("--browser", action="store_true", help="用默认浏览器代替桌面窗口")
    parser.add_argument("--watch-stdin", action="store_true", help="stdin 关闭时自动退出（由 Electron 托管时使用）")
    args = parser.parse_args(argv)

    base = app_root()
    resources = resource_root()
    logger = logging.getLogger("scoutmind.desktop")
    try:
        redirect_streams(base)
        logger = setup_logging(base)
        configure_environment(base, resources)
        logger.info("启动：base=%s resources=%s", base, resources)

        existing = read_instance(base)
        if existing and not args.headless:
            logger.info("检测到已运行实例，直接打开窗口")
            open_window(f"http://127.0.0.1:{existing['port']}", logger)
            return 0

        upgrade_database(resources, logger)
        # alembic 的 fileConfig 会重置日志配置，这里重新挂回文件日志
        logger = setup_logging(base)
        port = args.port or free_port()
        backend = Backend(port, logger)
        backend.start()
        write_instance(base, port)
        logger.info("后端就绪：%s", backend.url)

        if args.headless:
            logger.info("headless 模式，保持运行直到进程结束")
            if args.watch_stdin and sys.stdin is not None:
                threading.Thread(target=watch_parent, args=(sys.stdin, backend, logger), daemon=True).start()
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            finally:
                backend.stop()
            return 0

        if args.browser:
            import webbrowser

            webbrowser.open(backend.url)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            finally:
                backend.stop()
            return 0

        try:
            open_window(backend.url, logger)
        except Exception:  # noqa: BLE001 - 没有 WebView2 时退回浏览器
            logger.exception("桌面窗口启动失败，退回默认浏览器")
            import webbrowser

            webbrowser.open(backend.url)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        backend.stop()
        return 0
    except Exception as error:  # noqa: BLE001 - 窗口程序必须给出可见错误
        logger.exception("启动失败")
        if not args.headless:
            show_error(f"ScoutMind 启动失败：\n{error}\n\n详细日志见 logs/desktop.log")
        else:
            print(f"FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
