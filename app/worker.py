import asyncio
import logging
import signal

from telegram import Bot
from telegram.error import TelegramError

from app.config import settings
from app.db.database import init_database
from app.db.jobs import increment_job_retry, update_job_status
from app.services.media_processor import (
    MediaTooLongError,
    OutputFileTooLargeError,
    ProcessingUnavailableError,
    cleanup_path,
    process_audio,
    process_video,
)
from app.services.queue_service import (
    dequeue_media_job,
    move_to_dead_letter_queue,
    requeue_media_job,
)
from app.utils.logging_config import setup_logging


logger = logging.getLogger(__name__)

shutdown_requested = False


def request_shutdown(signum, frame) -> None:
    global shutdown_requested
    shutdown_requested = True
    logger.info("Shutdown requested. Worker will stop after current job.")


def _register_shutdown_handlers() -> None:
    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)


async def _retry_or_dead_letter(
    bot: Bot,
    payload: dict,
    chat_id: int,
    job_id: int,
    reason: str,
) -> None:
    retry_count = increment_job_retry(job_id)

    if retry_count <= settings.MAX_JOB_RETRIES:
        payload["attempt"] = retry_count
        requeue_media_job(payload)

        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Processing failed temporarily. I will retry this request.\n\n"
                f"Job ID: {job_id}\n"
                f"Retry: {retry_count}/{settings.MAX_JOB_RETRIES}"
            ),
        )

        logger.warning(
            "Requeued job %s retry %s/%s because: %s",
            job_id,
            retry_count,
            settings.MAX_JOB_RETRIES,
            reason,
        )

        return

    move_to_dead_letter_queue(payload, reason)
    update_job_status(job_id, "failed_permanent", reason)

    await bot.send_message(
        chat_id=chat_id,
        text=(
            "Processing failed after multiple attempts.\n\n"
            f"Job ID: {job_id}\n"
            "This request was moved to review."
        ),
    )

    logger.error("Moved job %s to dead-letter queue. Reason: %s", job_id, reason)


async def process_queued_job(bot: Bot, payload: dict) -> None:
    job_id = int(payload["job_id"])
    chat_id = int(payload["chat_id"])
    media_type = payload["media_type"]
    selected_value = payload["selected_value"]
    url = payload["url"]
    title = payload.get("title") or "media"

    processed = None

    try:
        logger.info("Starting job %s", job_id)
        update_job_status(job_id, "processing")

        await bot.send_message(
            chat_id=chat_id,
            text=f"Worker started processing your request.\n\nJob ID: {job_id}",
        )

        if media_type == "video":
            height = int(selected_value)
            processed = await process_video(url=url, height=height, title_hint=title)

        elif media_type == "audio":
            processed = await process_audio(url=url, title_hint=title)

        else:
            raise ProcessingUnavailableError("Unknown media type.")

        await bot.send_message(
            chat_id=chat_id,
            text="Processing complete. Uploading file to Telegram...",
        )

        with processed.file_path.open("rb") as file:
            if processed.media_type == "audio":
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=file,
                    filename=processed.display_filename,
                    caption="Processed audio. Temporary file will now be deleted.",
                )
            else:
                await bot.send_video(
                    chat_id=chat_id,
                    video=file,
                    filename=processed.display_filename,
                    caption="Processed video. Temporary file will now be deleted.",
                    supports_streaming=True,
                )

        update_job_status(job_id, "completed")
        logger.info("Completed job %s", job_id)

    except MediaTooLongError as error:
        reason = str(error)
        update_job_status(job_id, "rejected", reason)

        await bot.send_message(
            chat_id=chat_id,
            text=f"Cannot process this media.\n\nReason: {reason}",
        )

    except OutputFileTooLargeError as error:
        reason = str(error)
        update_job_status(job_id, "rejected", reason)

        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"Cannot send this file through Telegram.\n\nReason: {reason}\n\n"
                "Later we can solve this with cloud storage links or a local Telegram Bot API server."
            ),
        )

    except ProcessingUnavailableError as error:
        reason = str(error)
        await _retry_or_dead_letter(bot, payload, chat_id, job_id, reason)

    except TelegramError as error:
        reason = f"Telegram error: {error}"
        logger.exception("Telegram upload failed for job %s", job_id)
        await _retry_or_dead_letter(bot, payload, chat_id, job_id, reason)

    except Exception as error:
        reason = f"Unexpected error: {error}"
        logger.exception("Unexpected worker error for job %s", job_id)
        await _retry_or_dead_letter(bot, payload, chat_id, job_id, reason)

    finally:
        if processed is not None:
            cleanup_path(processed.file_path.parent)


async def worker_loop() -> None:
    settings.validate()
    init_database()

    bot = Bot(token=settings.BOT_TOKEN)

    logger.info("Worker started. Waiting for jobs from queue: %s", settings.QUEUE_NAME)

    while not shutdown_requested:
        payload = await asyncio.to_thread(dequeue_media_job)

        if payload is None:
            continue

        await process_queued_job(bot, payload)

    logger.info("Worker stopped gracefully.")


def main() -> None:
    setup_logging("worker.log")
    _register_shutdown_handlers()
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()