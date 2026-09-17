import runpy
from pathlib import Path
from unittest.mock import patch

from app.config import config


ROOT_DIR = Path(__file__).resolve().parent.parent


def test_main_starts_uvicorn_with_runtime_config():
    """
    服务启动入口只负责把运行配置交给 Uvicorn。这里 mock 真正的服务器启动，
    既避免测试占用端口，也确认监听地址、端口和热重载配置不会在入口层丢失。
    """
    with (
        patch.object(config, "listen_host", "127.0.0.1"),
        patch.object(config, "listen_port", 8765),
        patch.object(config, "reload_debug", True),
        patch("uvicorn.run") as run_server,
    ):
        runpy.run_path(str(ROOT_DIR / "main.py"), run_name="__main__")

    run_server.assert_called_once_with(
        app="app.asgi:app",
        host="127.0.0.1",
        port=8765,
        reload=True,
        log_level="warning",
    )


def test_non_loopback_api_requires_an_api_key():
    with (
        patch.object(config, "listen_host", "0.0.0.0"),
        patch.dict(config.app, {"api_key": ""}),
    ):
        try:
            config.validate_api_server_security()
        except RuntimeError as exc:
            assert "requires app.api_key" in str(exc)
        else:
            raise AssertionError("expected an insecure API configuration to fail")


def test_loopback_api_allows_empty_api_key_for_local_use():
    with (
        patch.object(config, "listen_host", "127.0.0.1"),
        patch.dict(config.app, {"api_key": ""}),
    ):
        config.validate_api_server_security()
