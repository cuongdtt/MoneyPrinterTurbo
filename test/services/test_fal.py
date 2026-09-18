import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import fal, material, state as sm, task as task_service


def _response(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload)


def test_fal_key_uses_dedicated_config_then_environment():
    with (
        patch.object(config, "app", {"fal_api_key": "configured"}),
        patch.dict(os.environ, {"FAL_KEY": "environment"}),
    ):
        assert fal.get_api_key() == "configured"
        config.app["fal_api_key"] = ""
        assert fal.get_api_key() == "environment"


def test_fal_submits_polls_and_returns_video_with_request_id():
    with (
        patch.object(config, "app", {"fal_api_key": "private-key"}),
        patch.object(
            fal.requests,
            "post",
            side_effect=[
                _response({"request_id": "req-123"}, 202),
                _response({"status": "IN_QUEUE"}),
                _response({"status": "COMPLETED"}),
                _response({"video": {"url": "https://v3.fal.media/video.mp4"}}),
            ],
        ) as post,
        patch.object(fal.time, "sleep"),
    ):
        items = fal.generate_videos("  sunrise  ", 2, VideoAspect.portrait)

    assert post.call_count == 4
    assert post.call_args_list[0].args[0] == fal.QUEUE_URL
    assert post.call_args_list[0].kwargs["headers"]["Authorization"] == "Key private-key"
    assert post.call_args_list[0].kwargs["json"] == {
        "prompt": "sunrise",
        "duration": "3",
        "aspect_ratio": "9:16",
    }
    request_url = f"{fal.QUEUE_URL}/requests/req-123"
    assert post.call_args_list[1].args[0] == f"{request_url}/status"
    assert post.call_args_list[2].args[0] == f"{request_url}/status"
    assert post.call_args_list[3].args[0] == request_url
    assert items[0].provider == "fal"
    assert items[0].duration == 3
    assert items[0].source_info["asset_id"] == "req-123"


def test_fal_does_not_repeat_ambiguous_paid_submission():
    with (
        patch.object(config, "app", {"fal_api_key": "private-key"}),
        patch.object(
            fal.requests,
            "post",
            side_effect=requests.Timeout("temporary timeout"),
        ) as post,
    ):
        with pytest.raises(fal.FalUnconfirmedTaskError):
            fal.generate_videos("sunrise", 5)
    post.assert_called_once()


def test_fal_poll_timeout_preserves_remote_request_id():
    with (
        patch.object(config, "app", {"fal_api_key": "private-key"}),
        patch.object(
            fal.requests,
            "post",
            side_effect=[_response({"request_id": "req-456"}, 202)]
            + [requests.Timeout()] * fal.MAX_POLL_FAILURES,
        ) as post,
        patch.object(fal.time, "sleep"),
    ):
        with pytest.raises(fal.FalUnconfirmedTaskError) as error:
            fal.generate_videos("sunrise", 5)
    assert error.value.request_id == "req-456"
    assert post.call_count == fal.MAX_POLL_FAILURES + 1


def test_fal_material_generation_stops_after_enough_downloaded_video():
    item = MaterialInfo(
        provider="fal",
        url="https://v3.fal.media/video.mp4",
        duration=5,
        source_info={"asset_id": "req-789", "search_term": "sunrise"},
    )
    with (
        patch.object(fal, "generate_videos", return_value=[item]) as generate,
        patch.object(
            material, "_save_generated_video_with_retry", return_value="/tmp/clip.mp4"
        ),
        patch.object(material, "_persist_material_sources") as persist,
    ):
        paths = material.download_videos(
            task_id="task-1",
            search_terms=["sunrise", "another term"],
            source="fal",
            audio_duration=4,
            max_clip_duration=5,
        )
    assert paths == ["/tmp/clip.mp4"]
    generate.assert_called_once()
    assert persist.call_args.args[1][0]["asset_id"] == "req-789"


def test_fal_download_failure_stops_new_paid_submissions():
    item = MaterialInfo(
        provider="fal",
        url="https://v3.fal.media/video.mp4",
        duration=5,
        source_info={"asset_id": "req-789"},
    )
    with (
        patch.object(fal, "generate_videos", return_value=[item]) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value=None),
        patch.object(material, "_persist_material_sources"),
    ):
        with pytest.raises(fal.FalDownloadError) as error:
            material.download_videos(
                task_id="task-1",
                search_terms=["sunrise", "another term"],
                source="fal",
                audio_duration=10,
                max_clip_duration=5,
            )
    assert error.value.request_id == "req-789"
    generate.assert_called_once()


def test_fal_task_preflight_rejects_missing_key_before_generation():
    params = VideoParams(video_subject="fal preflight", video_source="fal")
    memory_state = sm.MemoryState()
    with (
        patch.object(fal, "is_enabled", return_value=False),
        patch.object(task_service.sm, "state", memory_state),
        patch.object(task_service, "generate_script") as generate_script,
    ):
        result = task_service.start("fal-preflight", params, stop_at="materials")

    assert result["failed_stage"] == "preflight"
    assert "API key" in result["error"]
    generate_script.assert_not_called()


def test_fal_task_failure_records_remote_request_id():
    params = VideoParams(video_subject="fal failure", video_source="fal")
    memory_state = sm.MemoryState()
    error = fal.FalUnconfirmedTaskError("remote state unknown", "req-recover")
    with (
        patch.object(task_service.sm, "state", memory_state),
        patch.object(task_service.material, "download_videos", side_effect=error),
    ):
        result = task_service.get_video_materials(
            task_id="fal-material-error",
            params=params,
            video_terms=["scene"],
            audio_duration=5,
        )

    assert result is None
    failed = memory_state.get_task("fal-material-error")
    assert failed["failed_stage"] == "materials"
    assert failed["fal_request_id"] == "req-recover"
