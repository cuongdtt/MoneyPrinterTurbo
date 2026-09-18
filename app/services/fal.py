"""fal.ai queued text-to-video generation for one verified model endpoint."""

import math
import os
import time
from typing import Any, Mapping
from urllib.parse import quote, urlsplit

import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect


MODEL_ID = "fal-ai/kling-video/v3/turbo/standard/text-to-video"
QUEUE_URL = f"https://queue.fal.run/{MODEL_ID}"
MIN_DURATION = 3
MAX_DURATION = 15
POLL_INTERVAL = 5.0
RUN_TIMEOUT = 1800.0
MAX_POLL_FAILURES = 5


class FalError(RuntimeError):
    def __init__(self, message: str, request_id: str = ""):
        super().__init__(message)
        self.request_id = request_id


class FalUnconfirmedTaskError(FalError):
    """A submitted request may still finish and incur a charge."""


class FalDownloadError(FalError):
    """The paid request completed, but its video could not be saved locally."""


def get_api_key(settings: Mapping[str, Any] | None = None) -> str:
    settings = config.app if settings is None else settings
    return (
        str(settings.get("fal_api_key", "") or "").strip()
        or os.getenv("FAL_KEY", "").strip()
    )


def is_enabled(settings: Mapping[str, Any] | None = None) -> bool:
    return bool(get_api_key(settings))


def _setting_seconds(key: str, default: float) -> float:
    try:
        value = float(config.app.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def _request_json(response: requests.Response, request_id: str = "") -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise FalUnconfirmedTaskError(
            "fal.ai returned an unreadable response; check the request in fal.ai",
            request_id,
        ) from exc
    if not isinstance(payload, dict):
        raise FalUnconfirmedTaskError(
            "fal.ai returned an unexpected response; check the request in fal.ai",
            request_id,
        )
    return payload


def _poll_request(request_id: str, headers: dict[str, str]) -> dict:
    request_url = f"{QUEUE_URL}/requests/{quote(request_id, safe='')}"
    deadline = time.monotonic() + _setting_seconds("fal_run_timeout", RUN_TIMEOUT)
    failures = 0
    interval = _setting_seconds("fal_poll_interval", POLL_INTERVAL)

    while time.monotonic() < deadline:
        try:
            response = requests.get(
                f"{request_url}/status",
                headers=headers,
                timeout=30,
                verify=config.app.get("tls_verify", True),
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                raise requests.HTTPError(response=response)
            if response.status_code >= 400:
                raise FalError(
                    f"fal.ai status lookup failed (HTTP {response.status_code})",
                    request_id,
                )
            status = _request_json(response, request_id)
            failures = 0
        except (requests.RequestException, FalUnconfirmedTaskError) as exc:
            failures += 1
            if failures >= MAX_POLL_FAILURES:
                raise FalUnconfirmedTaskError(
                    "fal.ai request status could not be confirmed; check the request in fal.ai",
                    request_id,
                ) from exc
            time.sleep(interval)
            continue

        state = status.get("status")
        if state == "COMPLETED":
            if status.get("error"):
                raise FalError("fal.ai video generation failed", request_id)
            break
        if state not in {"IN_QUEUE", "IN_PROGRESS"}:
            raise FalUnconfirmedTaskError(
                "fal.ai returned an unknown request status; check the request in fal.ai",
                request_id,
            )
        time.sleep(interval)
    else:
        raise FalUnconfirmedTaskError(
            "fal.ai request timed out locally; check the request in fal.ai",
            request_id,
        )

    try:
        response = requests.get(
            request_url,
            headers=headers,
            timeout=30,
            verify=config.app.get("tls_verify", True),
        )
    except requests.RequestException as exc:
        raise FalUnconfirmedTaskError(
            "fal.ai video completed but its result could not be retrieved",
            request_id,
        ) from exc
    if response.status_code >= 400:
        raise FalUnconfirmedTaskError(
            f"fal.ai video completed but result lookup failed (HTTP {response.status_code})",
            request_id,
        )
    return _request_json(response, request_id)


def generate_videos(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> list[MaterialInfo]:
    api_key = get_api_key()
    if not api_key:
        raise FalError("fal.ai video generation requires an API key")
    prompt = str(search_term or "").strip()
    if not prompt:
        raise FalError("fal.ai search term must not be empty")
    try:
        requested_duration = int(minimum_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FalError("fal.ai clip duration must be a positive integer") from exc
    if requested_duration <= 0:
        raise FalError("fal.ai clip duration must be a positive integer")
    duration = min(max(requested_duration, MIN_DURATION), MAX_DURATION)
    aspect = VideoAspect(video_aspect)
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}

    # A timed-out submission may already have created a paid request. Never resubmit.
    try:
        response = requests.post(
            QUEUE_URL,
            headers=headers,
            json={
                "prompt": prompt,
                "duration": str(duration),
                "aspect_ratio": aspect.value,
            },
            timeout=30,
            verify=config.app.get("tls_verify", True),
        )
    except requests.RequestException as exc:
        raise FalUnconfirmedTaskError(
            "fal.ai submission outcome is unknown; check recent requests in fal.ai"
        ) from exc
    if response.status_code >= 500:
        raise FalUnconfirmedTaskError(
            f"fal.ai submission outcome is unknown (HTTP {response.status_code}); check recent requests in fal.ai"
        )
    if response.status_code >= 400:
        raise FalError(
            f"fal.ai rejected video generation (HTTP {response.status_code})"
        )
    submission = _request_json(response)
    request_id = str(submission.get("request_id") or "").strip()
    if not request_id:
        raise FalUnconfirmedTaskError(
            "fal.ai did not return a request ID; check recent requests in fal.ai"
        )

    result = _poll_request(request_id, headers)
    video = result.get("video")
    url = video.get("url") if isinstance(video, dict) else None
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
    except ValueError:
        parsed = None
    if not parsed or parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise FalError("fal.ai completed without a usable video URL", request_id)
    return [
        MaterialInfo(
            provider="fal",
            url=url,
            duration=duration,
            source_info={
                "provider": "fal",
                "asset_id": request_id,
                "search_term": prompt,
            },
        )
    ]
