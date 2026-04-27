import asyncio
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp

from app.config import DOWNLOADS_DIR, settings


class MediaProcessingError(Exception):
    """Base error for media processing."""


class MediaTooLongError(MediaProcessingError):
    """Raised when media duration exceeds allowed limit."""


class OutputFileTooLargeError(MediaProcessingError):
    """Raised when processed file is too large to send."""


class ProcessingUnavailableError(MediaProcessingError):
    """Raised when processing fails for a general reason."""


@dataclass
class ProcessedMedia:
    file_path: Path
    display_filename: str
    media_type: str


def _safe_title(value: str) -> str:
    """
    Create a safe filename segment.

    This prevents weird characters from becoming part of the output filename.
    """
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_ "
    cleaned = "".join(char for char in value if char in allowed).strip()
    return cleaned[:60] or "media"


def _make_job_dir() -> Path:
    """
    Each user request gets a unique temporary folder.

    This prevents two users from overwriting each other's files.
    """
    job_id = str(uuid.uuid4())
    job_dir = DOWNLOADS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def cleanup_path(path: Path) -> None:
    """
    Delete a file or folder safely.

    We call this after sending the file to Telegram.
    """
    try:
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        # Cleanup failure should not crash the bot.
        pass


def _check_file_size(file_path: Path) -> None:
    size_mb = file_path.stat().st_size / (1024 * 1024)

    if size_mb > settings.MAX_OUTPUT_FILE_MB:
        raise OutputFileTooLargeError(
            f"Processed file is {size_mb:.1f} MB, which is above the {settings.MAX_OUTPUT_FILE_MB} MB limit."
        )


def _validate_duration(info: dict[str, Any]) -> None:
    duration = info.get("duration")

    if duration is None:
        return

    try:
        duration_int = int(duration)
    except (TypeError, ValueError):
        return

    if duration_int > settings.MAX_MEDIA_DURATION_SECONDS:
        raise MediaTooLongError(
            f"This media is too long. Current limit is {settings.MAX_MEDIA_DURATION_SECONDS // 60} minutes."
        )


def _find_output_file(job_dir: Path) -> Path:
    files = [path for path in job_dir.iterdir() if path.is_file()]

    if not files:
        raise ProcessingUnavailableError("Processing finished but no output file was created.")

    # Return the largest file, usually the final processed media.
    return max(files, key=lambda path: path.stat().st_size)


def _base_yt_dlp_options(job_dir: Path) -> dict[str, Any]:
    """
    Shared safe yt-dlp options.

    We still do not use cookies, browser sessions, or login credentials.
    """
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        "outtmpl": str(job_dir / "%(title).60s.%(ext)s"),
        "restrictfilenames": True,
    }


def _process_audio_sync(url: str, title_hint: str) -> ProcessedMedia:
    job_dir = _make_job_dir()

    try:
        options = _base_yt_dlp_options(job_dir)

        options.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
        )

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            _validate_duration(info)

        file_path = _find_output_file(job_dir)
        _check_file_size(file_path)

        safe_title = _safe_title(title_hint)
        display_filename = f"{safe_title}.mp3"

        return ProcessedMedia(
            file_path=file_path,
            display_filename=display_filename,
            media_type="audio",
        )

    except Exception:
        cleanup_path(job_dir)
        raise


def _process_video_sync(url: str, height: int, title_hint: str) -> ProcessedMedia:
    job_dir = _make_job_dir()

    try:
        options = _base_yt_dlp_options(job_dir)

        # This asks for the best video up to selected height plus best audio.
        # If merging is needed, yt-dlp uses FFmpeg.
        options.update(
            {
                "format": f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best",
                "merge_output_format": "mp4",
            }
        )

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            _validate_duration(info)

        file_path = _find_output_file(job_dir)
        _check_file_size(file_path)

        safe_title = _safe_title(title_hint)
        display_filename = f"{safe_title}_{height}p.mp4"

        return ProcessedMedia(
            file_path=file_path,
            display_filename=display_filename,
            media_type="video",
        )

    except Exception:
        cleanup_path(job_dir)
        raise


async def process_audio(url: str, title_hint: str) -> ProcessedMedia:
    try:
        return await asyncio.to_thread(_process_audio_sync, url, title_hint)

    except MediaTooLongError:
        raise

    except OutputFileTooLargeError:
        raise

    except Exception as error:
        raise ProcessingUnavailableError(
            "Audio processing failed. The platform may have blocked extraction, or the media format may be unsupported."
        ) from error


async def process_video(url: str, height: int, title_hint: str) -> ProcessedMedia:
    try:
        return await asyncio.to_thread(_process_video_sync, url, height, title_hint)

    except MediaTooLongError:
        raise

    except OutputFileTooLargeError:
        raise

    except Exception as error:
        raise ProcessingUnavailableError(
            "Video processing failed. The platform may have blocked extraction, or the media format may be unsupported."
        ) from error