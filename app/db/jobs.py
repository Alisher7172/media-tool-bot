from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.database import get_session
from app.db.models import Job


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_job(
    telegram_user_id: int,
    username: str | None,
    chat_id: int,
    url: str,
    media_title: str | None,
    media_type: str,
    selected_quality: str,
    status: str = "queued",
) -> int:
    with get_session() as session:
        job = Job(
            telegram_user_id=telegram_user_id,
            username=username,
            chat_id=chat_id,
            url=url,
            media_title=media_title,
            media_type=media_type,
            selected_quality=selected_quality,
            status=status,
            queued_at=_utc_now(),
            retry_count=0,
        )

        session.add(job)
        session.flush()

        return int(job.id)


def update_job_status(
    job_id: int,
    status: str,
    error_message: str | None = None,
) -> None:
    with get_session() as session:
        job = session.get(Job, job_id)

        if job is None:
            return

        job.status = status
        job.error_message = error_message
        job.updated_at = _utc_now()

        if status == "processing":
            job.started_at = _utc_now()

        elif status in {"completed", "failed", "rejected", "failed_permanent"}:
            job.completed_at = _utc_now()


def increment_job_retry(job_id: int) -> int:
    with get_session() as session:
        job = session.get(Job, job_id)

        if job is None:
            return 0

        job.retry_count = int(job.retry_count or 0) + 1
        job.last_retry_at = _utc_now()
        job.status = "retrying"
        job.updated_at = _utc_now()

        session.flush()

        return int(job.retry_count)


def count_user_jobs_today(telegram_user_id: int) -> int:
    now = datetime.now(timezone.utc)
    start_of_day = datetime(
        year=now.year,
        month=now.month,
        day=now.day,
        tzinfo=timezone.utc,
    ).replace(tzinfo=None)

    with get_session() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.telegram_user_id == telegram_user_id)
            .where(Job.created_at >= start_of_day)
        )

        return int(count or 0)


def get_last_user_job_time(telegram_user_id: int) -> datetime | None:
    with get_session() as session:
        job = session.scalar(
            select(Job)
            .where(Job.telegram_user_id == telegram_user_id)
            .order_by(Job.created_at.desc())
            .limit(1)
        )

        if job is None:
            return None

        if job.created_at.tzinfo is None:
            return job.created_at.replace(tzinfo=timezone.utc)

        return job.created_at


def get_job(job_id: int) -> dict | None:
    with get_session() as session:
        job = session.get(Job, job_id)

        if job is None:
            return None

        return {
            "id": job.id,
            "telegram_user_id": job.telegram_user_id,
            "username": job.username,
            "chat_id": job.chat_id,
            "url": job.url,
            "media_title": job.media_title,
            "media_type": job.media_type,
            "selected_quality": job.selected_quality,
            "status": job.status,
            "error_message": job.error_message,
            "retry_count": job.retry_count,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "queued_at": job.queued_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
        }


def get_job_status_counts() -> dict[str, int]:
    with get_session() as session:
        rows = session.execute(
            select(Job.status, func.count(Job.id))
            .group_by(Job.status)
            .order_by(func.count(Job.id).desc())
        ).all()

        return {status: int(count) for status, count in rows}


def count_jobs_today() -> int:
    now = datetime.now(timezone.utc)
    start_of_day = datetime(
        year=now.year,
        month=now.month,
        day=now.day,
        tzinfo=timezone.utc,
    ).replace(tzinfo=None)

    with get_session() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.created_at >= start_of_day)
        )

        return int(count or 0)


def get_recent_failed_jobs(limit: int = 10) -> list[dict]:
    with get_session() as session:
        jobs = session.scalars(
            select(Job)
            .where(Job.status.in_(["failed", "failed_permanent"]))
            .order_by(Job.created_at.desc())
            .limit(limit)
        ).all()

        return [
            {
                "id": job.id,
                "telegram_user_id": job.telegram_user_id,
                "username": job.username,
                "chat_id": job.chat_id,
                "url": job.url,
                "media_title": job.media_title,
                "media_type": job.media_type,
                "selected_quality": job.selected_quality,
                "status": job.status,
                "error_message": job.error_message,
                "retry_count": job.retry_count,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
            }
            for job in jobs
        ]