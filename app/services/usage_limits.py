from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import settings
from app.db.jobs import count_user_jobs_today, get_last_user_job_time


@dataclass
class UsageCheckResult:
    allowed: bool
    reason: str | None = None


def check_user_usage_allowed(telegram_user_id: int) -> UsageCheckResult:
    daily_count = count_user_jobs_today(telegram_user_id)

    if daily_count >= settings.DAILY_REQUEST_LIMIT:
        return UsageCheckResult(
            allowed=False,
            reason=(
                f"You have reached the daily free limit of "
                f"{settings.DAILY_REQUEST_LIMIT} requests."
            ),
        )

    last_job_time = get_last_user_job_time(telegram_user_id)

    if last_job_time is not None:
        now = datetime.now(timezone.utc)
        elapsed = (now - last_job_time).total_seconds()

        if elapsed < settings.USER_COOLDOWN_SECONDS:
            wait_seconds = int(settings.USER_COOLDOWN_SECONDS - elapsed)

            return UsageCheckResult(
                allowed=False,
                reason=f"Please wait {wait_seconds} seconds before starting another request.",
            )

    return UsageCheckResult(allowed=True)