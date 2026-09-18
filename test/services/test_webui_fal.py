from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config


WEBUI_MAIN = Path(__file__).resolve().parents[2] / "webui" / "Main.py"


def _widget_by_key(elements, key):
    return next(
        item
        for item in elements
        if str(getattr(item, "key", "")) == key
        or str(getattr(item, "key", "")).startswith(f"{key}_")
    )


def test_fal_requires_confirmation_and_does_not_put_key_in_task_params():
    settings = dict(
        config.app,
        llm_provider="openai",
        video_source="pexels",
        fal_api_key="fal-secret",
    )
    with (
        patch.object(config, "app", settings),
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.webui_task.submit_generation") as submit_generation,
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        _widget_by_key(app.text_area, "video_subject").set_value("AI office").run()
        _widget_by_key(app.text_area, "video_script").set_value(
            "AI helps people work faster."
        ).run()
        _widget_by_key(app.text_area, "video_terms").set_value("office worker").run()
        app.session_state["video_source_select_en"] = "fal"
        app.run()

        _widget_by_key(app.button, "generate_video_button").click().run()
        assert submit_generation.call_count == 0
        assert any("confirm" in str(item.value).lower() for item in app.error)

        _widget_by_key(app.checkbox, "fal_confirm_charge").check().run()
        _widget_by_key(app.button, "generate_video_button").click().run()

        assert submit_generation.call_count == 1
        params = submit_generation.call_args.kwargs["params"]
        assert params.video_source == "fal"
        assert "fal-secret" not in params.model_dump_json()
        assert not app.exception
