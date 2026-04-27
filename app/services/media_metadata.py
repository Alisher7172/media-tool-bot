import asyncio
from dataclasses import dataclass
from typing import Any

import yt_dlp


class MetadataExtractionError(Exception):
    """Base error for media metadata extraction."""


class PrivateOrLoginRequiredError(MetadataExtractionError):
    """Raised when content appears private, login-required, or restricted."""


class UnsupportedMediaError(MetadataExtractionError):
    """Raised when content is unsupported or not suitable for processing."""


@dataclass
class VideoOption:
    quality: str
    height: int
    ext: str


@dataclass
class AudioOption:
    quality: str
    abr: int | None
    ext: str


@dataclass
class MediaMetadata:
    title: str
    uploader: str | None
    duration: int | None
    webpage_url: str
    video_options: list[VideoOption]
    audio_options: list[AudioOption]


PRIVATE_OR_LOGIN_MARKERS = [
    "private video",
    "login",
    "log in",
    "sign in",
    "signin",
    "cookies",
    "authentication",
    "not available",
    "members-only",
    "premium",
    "age-restricted",
    "confirm your age",
    "requires payment",
]


def _yt_dlp_options() -> dict[str, Any]:
    """
    Safe metadata-only config.

    We intentionally do NOT use:
    - cookies
    - browser cookies
    - username/password
    - netrc
    - geo-bypass tricks
    - playlist downloading

    This keeps the bot aligned with public-content-only behavior.
    """
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "socket_timeout": 15,
        "retries": 2,
        "fragment_retries": 1,
        "ignoreerrors": False,
    }


def _looks_private_or_login_required(error_message: str) -> bool:
    lowered = error_message.lower()
    return any(marker in lowered for marker in PRIVATE_OR_LOGIN_MARKERS)


def _extract_metadata_sync(url: str) -> dict[str, Any]:
    with yt_dlp.YoutubeDL(_yt_dlp_options()) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise UnsupportedMediaError("No public metadata was found for this link.")

    return info


def _duration_to_text(seconds: int | None) -> str:
    if seconds is None:
        return "Unknown"

    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}h {minutes}m {sec}s"

    return f"{minutes}m {sec}s"


def _build_video_options(formats: list[dict[str, Any]]) -> list[VideoOption]:
    best_by_height: dict[int, VideoOption] = {}

    for fmt in formats:
        vcodec = fmt.get("vcodec")
        height = fmt.get("height")
        ext = fmt.get("ext") or "unknown"

        if not height:
            continue

        if vcodec == "none":
            continue

        try:
            height_int = int(height)
        except (TypeError, ValueError):
            continue

        if height_int < 144:
            continue

        current = best_by_height.get(height_int)

        if current is None:
            best_by_height[height_int] = VideoOption(
                quality=f"{height_int}p",
                height=height_int,
                ext=ext,
            )

    return [
        best_by_height[h]
        for h in sorted(best_by_height.keys(), reverse=True)
    ][:6]


def _build_audio_options(formats: list[dict[str, Any]]) -> list[AudioOption]:
    audio_formats: list[AudioOption] = []

    for fmt in formats:
        acodec = fmt.get("acodec")
        vcodec = fmt.get("vcodec")
        abr = fmt.get("abr")
        ext = fmt.get("ext") or "unknown"

        if acodec == "none":
            continue

        # Prefer audio-only formats for audio extraction.
        if vcodec != "none":
            continue

        abr_int: int | None = None
        if abr is not None:
            try:
                abr_int = int(float(abr))
            except (TypeError, ValueError):
                abr_int = None

        label = f"{abr_int}kbps" if abr_int else "Best audio"

        audio_formats.append(
            AudioOption(
                quality=label,
                abr=abr_int,
                ext=ext,
            )
        )

    # Sort by bitrate, best first. Unknown bitrates go last.
    audio_formats.sort(key=lambda item: item.abr or 0, reverse=True)

    cleaned: list[AudioOption] = []
    seen: set[str] = set()

    for option in audio_formats:
        key = option.quality
        if key in seen:
            continue

        seen.add(key)
        cleaned.append(option)

    if not cleaned:
        cleaned.append(
            AudioOption(
                quality="Best audio",
                abr=None,
                ext="mp3",
            )
        )

    return cleaned[:4]


def _normalize_metadata(info: dict[str, Any]) -> MediaMetadata:
    if info.get("_type") == "playlist":
        raise UnsupportedMediaError(
            "Playlists are not supported yet. Please send a single public media link."
        )

    formats = info.get("formats") or []

    if not formats:
        raise UnsupportedMediaError(
            "No public formats were found for this link."
        )

    return MediaMetadata(
        title=info.get("title") or "Untitled media",
        uploader=info.get("uploader") or info.get("channel"),
        duration=info.get("duration"),
        webpage_url=info.get("webpage_url") or "",
        video_options=_build_video_options(formats),
        audio_options=_build_audio_options(formats),
    )


async def extract_public_metadata(url: str) -> MediaMetadata:
    try:
        info = await asyncio.to_thread(_extract_metadata_sync, url)
        return _normalize_metadata(info)

    except yt_dlp.utils.DownloadError as error:
        message = str(error)

        if _looks_private_or_login_required(message):
            raise PrivateOrLoginRequiredError(
                "This content appears to be private, login-required, restricted, or unavailable."
            ) from error

        raise MetadataExtractionError(
            "I could not safely inspect this link. It may be unsupported or temporarily unavailable."
        ) from error

    except PrivateOrLoginRequiredError:
        raise

    except UnsupportedMediaError:
        raise

    except Exception as error:
        raise MetadataExtractionError(
            "Unexpected error while inspecting the media link."
        ) from error


def format_duration(seconds: int | None) -> str:
    return _duration_to_text(seconds)