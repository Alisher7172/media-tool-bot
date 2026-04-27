import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.db.jobs import count_jobs_today, get_job_status_counts
from app.services.queue_service import get_dead_letter_queue_length, get_queue_length

from app.services.queue_service import MediaJobPayload, enqueue_media_job, get_job_position

from app.services.link_validator import extract_url, is_supported_public_url
from app.services.media_metadata import (
    MetadataExtractionError,
    PrivateOrLoginRequiredError,
    UnsupportedMediaError,
    extract_public_metadata,
    format_duration,
)


from app.config import settings
from app.db.jobs import create_job, update_job_status
from app.services.usage_limits import check_user_usage_allowed


DISCLAIMER = """
<b>Welcome to Media Tool Bot.</b>

Send me a public media link and I will check what processing options may be available.

<b>Important:</b>
• Only public links are supported.
• Do not send private, login-required, or copyrighted content you do not have rights to use.
• You are responsible for making sure you have permission to process the content.
• This bot does not permanently store processed files.
• Temporary files are deleted after delivery.
• Fair usage limits apply to protect service stability.

Current phase: controlled media processing with safety limits.
"""


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        DISCLAIMER,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send a public YouTube, Instagram, or TikTok link. "
        "I will inspect public metadata first, then show available processing options."
    )


def _build_options_keyboard(video_options, audio_options) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []

    if video_options:
        keyboard.append([
            InlineKeyboardButton("🎬 Video options", callback_data="noop:video_header")
        ])

        row: list[InlineKeyboardButton] = []

        for option in video_options:
            row.append(
                InlineKeyboardButton(
                    option.quality,
                    callback_data=f"video:{option.height}",
                )
            )

            if len(row) == 3:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

    if audio_options:
        keyboard.append([
            InlineKeyboardButton("🎧 Audio options", callback_data="noop:audio_header")
        ])

        row = []

        for index, option in enumerate(audio_options):
            callback_value = option.abr if option.abr else "best"

            row.append(
                InlineKeyboardButton(
                    option.quality,
                    callback_data=f"audio:{callback_value}",
                )
            )

            if len(row) == 2:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton("❌ Cancel", callback_data="cancel")
    ])

    return InlineKeyboardMarkup(keyboard)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""

    url = extract_url(text)

    if not url:
        await update.message.reply_text(
            "Please send a valid public media link."
        )
        return

    is_valid, reason = is_supported_public_url(url)

    if not is_valid:
        await update.message.reply_text(
            f"Cannot process this link.\n\nReason: {reason}"
        )
        return

    status_message = await update.message.reply_text(
        "Inspecting public metadata. No file is being downloaded yet..."
    )

    try:
        metadata = await extract_public_metadata(url)

    except PrivateOrLoginRequiredError as error:
        await status_message.edit_text(
            f"Cannot process this link.\n\nReason: {error}"
        )
        return

    except UnsupportedMediaError as error:
        await status_message.edit_text(
            f"Unsupported media.\n\nReason: {error}"
        )
        return

    except MetadataExtractionError as error:
        await status_message.edit_text(
            f"Could not inspect this link.\n\nReason: {error}"
        )
        return

    context.user_data["pending_media"] = {
        "url": url,
        "title": metadata.title,
        "duration": metadata.duration,
    }

    safe_title = html.escape(metadata.title)
    safe_uploader = html.escape(metadata.uploader or "Unknown")
    duration_text = format_duration(metadata.duration)

    keyboard = _build_options_keyboard(
        metadata.video_options,
        metadata.audio_options,
    )

    if not metadata.video_options and not metadata.audio_options:
        await status_message.edit_text(
            "I found public metadata, but no processable video or audio formats."
        )
        return

    await status_message.edit_text(
        text=(
            "<b>Media found</b>\n\n"
            f"<b>Title:</b> {safe_title}\n"
            f"<b>Uploader:</b> {safe_uploader}\n"
            f"<b>Duration:</b> {duration_text}\n\n"
            "Choose an option below.\n\n"
            "<i>Phase 2 only confirms your choice. Actual downloading comes in Phase 3.</i>"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )



async def option_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    await query.answer()

    data = query.data or ""

    if data.startswith("noop:"):
        return

    if data == "cancel":
        context.user_data.pop("pending_media", None)

        await query.edit_message_text(
            "Request cancelled. Send another public link when ready."
        )
        return

    pending_media = context.user_data.get("pending_media")

    if not pending_media:
        await query.edit_message_text(
            "This selection expired. Please send the link again."
        )
        return

    user = query.from_user
    telegram_user_id = user.id
    username = user.username
    chat_id = query.message.chat_id

    usage_check = check_user_usage_allowed(telegram_user_id)

    if not usage_check.allowed:
        await query.edit_message_text(
            f"Request blocked by fair usage limits.\n\nReason: {usage_check.reason}"
        )
        return

    media_type, selected_value = data.split(":", maxsplit=1)

    url = pending_media["url"]
    title = pending_media.get("title", "media")
    duration = pending_media.get("duration")

    if duration is not None:
        try:
            duration_int = int(duration)
        except (TypeError, ValueError):
            duration_int = None

        if duration_int is not None and duration_int > settings.MAX_MEDIA_DURATION_SECONDS:
            await query.edit_message_text(
                "Cannot process this media.\n\n"
                f"Reason: This media is longer than the current "
                f"{settings.MAX_MEDIA_DURATION_SECONDS // 60}-minute limit."
            )
            return

    job_id = create_job(
        telegram_user_id=telegram_user_id,
        username=username,
        chat_id=chat_id,
        url=url,
        media_title=title,
        media_type=media_type,
        selected_quality=selected_value,
        status="queued",
    )

    try:
        enqueue_media_job(
            MediaJobPayload(
                job_id=job_id,
                chat_id=chat_id,
                telegram_user_id=telegram_user_id,
                username=username,
                url=url,
                title=title,
                media_type=media_type,
                selected_value=selected_value,
            )
        )

    except Exception as error:
        update_job_status(job_id, "failed", f"Failed to enqueue job: {error}")

        await query.edit_message_text(
            "Could not queue this request.\n\n"
            "Reason: Redis queue is unavailable. Please make sure Redis is running."
        )
        return

    context.user_data.pop("pending_media", None)

    position = get_job_position(job_id)

    position_text = (
        f"Queue position: {position}\n\n"
        if position is not None
        else ""
    )

    await query.edit_message_text(
        "Your request has been queued.\n\n"
        f"Job ID: {job_id}\n"
        f"{position_text}"
        "A worker will process it shortly. You can keep using Telegram while it runs."
    )

    query = update.callback_query

    await query.answer()

    data = query.data or ""

    if data.startswith("noop:"):
        return

    if data == "cancel":
        context.user_data.pop("pending_media", None)

        await query.edit_message_text(
            "Request cancelled. Send another public link when ready."
        )
        return

    pending_media = context.user_data.get("pending_media")

    if not pending_media:
        await query.edit_message_text(
            "This selection expired. Please send the link again."
        )
        return

    user = query.from_user
    telegram_user_id = user.id
    username = user.username

    usage_check = check_user_usage_allowed(telegram_user_id)

    if not usage_check.allowed:
        await query.edit_message_text(
            f"Request blocked by fair usage limits.\n\nReason: {usage_check.reason}"
        )
        return

    media_type, selected_value = data.split(":", maxsplit=1)

    url = pending_media["url"]
    title = pending_media.get("title", "media")
    duration = pending_media.get("duration")

    if duration is not None:
        try:
            duration_int = int(duration)
        except (TypeError, ValueError):
            duration_int = None

        if duration_int is not None and duration_int > settings.MAX_MEDIA_DURATION_SECONDS:
            await query.edit_message_text(
                "Cannot process this media.\n\n"
                f"Reason: This media is longer than the current "
                f"{settings.MAX_MEDIA_DURATION_SECONDS // 60}-minute limit."
            )
            return

    selected_quality = selected_value

    job_id = create_job(
        telegram_user_id=telegram_user_id,
        username=username,
        url=url,
        media_title=title,
        media_type=media_type,
        selected_quality=selected_quality,
    )

    await query.edit_message_text(
        "Processing started.\n\n"
        f"Job ID: {job_id}\n\n"
        "Large or long media may be rejected automatically. "
        "Temporary files are deleted after delivery."
    )

    processed = None

    try:
        if media_type == "video":
            height = int(selected_value)
            processed = await process_video(url=url, height=height, title_hint=title)

        elif media_type == "audio":
            processed = await process_audio(url=url, title_hint=title)

        else:
            update_job_status(job_id, "failed", "Unknown media type.")
            await query.message.reply_text("Unknown processing option.")
            return

        await query.message.reply_text(
            "Processing complete. Uploading file to Telegram..."
        )

        with processed.file_path.open("rb") as file:
            if processed.media_type == "audio":
                await query.message.reply_audio(
                    audio=file,
                    filename=processed.display_filename,
                    caption="Processed audio. Temporary file will now be deleted.",
                )
            else:
                await query.message.reply_video(
                    video=file,
                    filename=processed.display_filename,
                    caption="Processed video. Temporary file will now be deleted.",
                    supports_streaming=True,
                )

        update_job_status(job_id, "completed")
        context.user_data.pop("pending_media", None)

    except MediaTooLongError as error:
        update_job_status(job_id, "rejected", str(error))
        await query.message.reply_text(f"Cannot process this media.\n\nReason: {error}")

    except OutputFileTooLargeError as error:
        update_job_status(job_id, "rejected", str(error))
        await query.message.reply_text(
            f"Cannot send this file through Telegram.\n\nReason: {error}\n\n"
            "Later we can solve this with cloud storage links or a local Telegram Bot API server."
        )

    except ProcessingUnavailableError as error:
        update_job_status(job_id, "failed", str(error))
        await query.message.reply_text(f"Processing failed.\n\nReason: {error}")

    except TelegramError as error:
        update_job_status(job_id, "failed", str(error))
        await query.message.reply_text(
            "Telegram rejected the upload. The file may be too large or unsupported."
        )

    except Exception as error:
        update_job_status(job_id, "failed", str(error))
        await query.message.reply_text(
            "Unexpected error while processing this request."
        )

    finally:
        if processed is not None:
            cleanup_path(processed.file_path.parent)
    query = update.callback_query

    await query.answer()

    data = query.data or ""

    if data.startswith("noop:"):
        return

    if data == "cancel":
        context.user_data.pop("pending_media", None)

        await query.edit_message_text(
            "Request cancelled. Send another public link when ready."
        )
        return

    pending_media = context.user_data.get("pending_media")

    if not pending_media:
        await query.edit_message_text(
            "This selection expired. Please send the link again."
        )
        return

    media_type, selected_value = data.split(":", maxsplit=1)

    url = pending_media["url"]
    title = pending_media.get("title", "media")

    await query.edit_message_text(
        "Processing started.\n\n"
        "Please keep this request reasonable. Large or long media may be rejected automatically."
    )

    processed = None

    try:
        if media_type == "video":
            height = int(selected_value)
            processed = await process_video(url=url, height=height, title_hint=title)

        elif media_type == "audio":
            processed = await process_audio(url=url, title_hint=title)

        else:
            await query.message.reply_text("Unknown processing option.")
            return

        await query.message.reply_text(
            "Processing complete. Uploading file to Telegram..."
        )

        with processed.file_path.open("rb") as file:
            if processed.media_type == "audio":
                await query.message.reply_audio(
                    audio=file,
                    filename=processed.display_filename,
                    caption="Processed audio. Temporary file will now be deleted.",
                )
            else:
                await query.message.reply_video(
                    video=file,
                    filename=processed.display_filename,
                    caption="Processed video. Temporary file will now be deleted.",
                    supports_streaming=True,
                )

        context.user_data.pop("pending_media", None)

    except MediaTooLongError as error:
        await query.message.reply_text(f"Cannot process this media.\n\nReason: {error}")

    except OutputFileTooLargeError as error:
        await query.message.reply_text(
            f"Cannot send this file through Telegram.\n\nReason: {error}\n\n"
            "Later we can solve this with cloud storage links or a local Telegram Bot API server."
        )

    except ProcessingUnavailableError as error:
        await query.message.reply_text(f"Processing failed.\n\nReason: {error}")

    except TelegramError as error:
        await query.message.reply_text(
            "Telegram rejected the upload. The file may be too large or unsupported."
        )

    except Exception:
        await query.message.reply_text(
            "Unexpected error while processing this request."
        )

    finally:
        if processed is not None:
            cleanup_path(processed.file_path.parent)


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if user_id not in settings.ADMIN_USER_IDS:
        await update.message.reply_text("You are not allowed to use this command.")
        return

    queue_length = get_queue_length()
    dead_letter_length = get_dead_letter_queue_length()
    jobs_today = count_jobs_today()
    status_counts = get_job_status_counts()

    status_lines = []

    if status_counts:
        for status, count in status_counts.items():
            status_lines.append(f"• {status}: {count}")
    else:
        status_lines.append("No jobs recorded yet.")

    await update.message.reply_text(
        "Bot stats\n\n"
        f"Jobs today: {jobs_today}\n"
        f"Queue length: {queue_length}\n"
        f"Dead-letter queue: {dead_letter_length}\n\n"
        "Job statuses:\n"
        + "\n".join(status_lines)
    )