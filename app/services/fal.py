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


def _error_detail(payload: Any) -> str:
    if isinstance(payload, dict) and ("detail" in payload or "error" in payload):
        detail = payload.get("detail", payload.get("error"))
    else:
        detail = payload
    if isinstance(detail, list):
        messages = [_error_detail(item) for item in detail]
        return "; ".join(message for message in messages if message)
    if isinstance(detail, dict):
        message = detail.get("msg") or detail.get("message")
        error_type = detail.get("type")
        if isinstance(message, str) and message.strip():
            return (
                f"{error_type}: {message.strip()}"
                if isinstance(error_type, str) and error_type.strip()
                else message.strip()
            )
    if isinstance(detail, str):
        return detail.strip()
    return ""


def _response_error_detail(response: requests.Response) -> str:
    try:
        return _error_detail(response.json())
    except ValueError:
        return ""


def _queue_link(submission: dict, field: str, fallback: str, request_id: str) -> str:
    link = submission.get(field)
    if not link:
        return fallback
    try:
        parsed = urlsplit(link) if isinstance(link, str) else None
    except ValueError:
        parsed = None
    if (
        not parsed
        or parsed.scheme != "https"
        or parsed.hostname != "queue.fal.run"
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise FalUnconfirmedTaskError(
            f"fal.ai returned an invalid {field}; check the request in fal.ai",
            request_id,
        )
    return link


def _poll_request(
    request_id: str,
    headers: dict[str, str],
    status_url: str,
    response_url: str,
) -> dict:
    deadline = time.monotonic() + _setting_seconds("fal_run_timeout", RUN_TIMEOUT)
    failures = 0
    interval = _setting_seconds("fal_poll_interval", POLL_INTERVAL)

    while time.monotonic() < deadline:
        try:
            response = requests.get(
                status_url,
                headers=headers,
                timeout=30,
                verify=config.app.get("tls_verify", True),
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                raise requests.HTTPError(response=response)
            if response.status_code >= 400:
                detail = _response_error_detail(response)
                raise FalError(
                    f"fal.ai status lookup failed (HTTP {response.status_code})"
                    + (f": {detail}" if detail else ""),
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
                detail = _error_detail(status.get("error"))
                raise FalError(
                    "fal.ai video generation failed"
                    + (f": {detail}" if detail else ""),
                    request_id,
                )
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
            response_url,
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
        detail = _response_error_detail(response)
        raise FalUnconfirmedTaskError(
            f"fal.ai video completed but result lookup failed (HTTP {response.status_code})"
            + (f": {detail}" if detail else ""),
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
        detail = _response_error_detail(response)
        raise FalUnconfirmedTaskError(
            f"fal.ai submission outcome is unknown (HTTP {response.status_code}); check recent requests in fal.ai"
            + (f": {detail}" if detail else "")
        )
    if response.status_code >= 400:
        detail = _response_error_detail(response)
        raise FalError(
            f"fal.ai rejected video generation (HTTP {response.status_code})"
            + (f": {detail}" if detail else "")
        )
    submission = _request_json(response)
    request_id = str(submission.get("request_id") or "").strip()
    if not request_id:
        raise FalUnconfirmedTaskError(
            "fal.ai did not return a request ID; check recent requests in fal.ai"
        )

    request_url = f"{QUEUE_URL}/requests/{quote(request_id, safe='')}"
    status_url = _queue_link(
        submission, "status_url", f"{request_url}/status", request_id
    )
    response_url = _queue_link(
        submission, "response_url", request_url, request_id
    )
    result = _poll_request(request_id, headers, status_url, response_url)
    if result.get("error"):
        detail = _error_detail(result.get("error"))
        raise FalError(
            "fal.ai video generation failed"
            + (f": {detail}" if detail else ""),
            request_id,
        )
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
