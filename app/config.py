import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)


BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
LOGS_DIR = BASE_DIR / "logs"


def _parse_admin_ids(raw_value: str) -> set[int]:
    admin_ids: set[int] = set()

    for item in raw_value.split(","):
        item = item.strip()

        if not item:
            continue

        try:
            admin_ids.add(int(item))
        except ValueError:
            continue

    return admin_ids


class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///bot_data.sqlite3")

    # Processing limits
    MAX_MEDIA_DURATION_SECONDS: int = int(os.getenv("MAX_MEDIA_DURATION_SECONDS", "600"))
    MAX_OUTPUT_FILE_MB: int = int(os.getenv("MAX_OUTPUT_FILE_MB", "45"))

    # User safety limits
    USER_COOLDOWN_SECONDS: int = int(os.getenv("USER_COOLDOWN_SECONDS", "30"))
    DAILY_REQUEST_LIMIT: int = int(os.getenv("DAILY_REQUEST_LIMIT", "20"))

    # Queue settings
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    QUEUE_NAME: str = os.getenv("QUEUE_NAME", "media_jobs")
    DEAD_LETTER_QUEUE_NAME: str = os.getenv("DEAD_LETTER_QUEUE_NAME", "media_jobs_dead")
    MAX_JOB_RETRIES: int = int(os.getenv("MAX_JOB_RETRIES", "2"))

    # Admin settings
    ADMIN_USER_IDS: set[int] = _parse_admin_ids(os.getenv("ADMIN_USER_IDS", ""))

    @classmethod
    def validate(cls) -> None:
        if not cls.BOT_TOKEN:
            raise RuntimeError("BOT_TOKEN is missing. Add it to your .env file.")

        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()