import logging
from logging.handlers import RotatingFileHandler

from app.config import LOGS_DIR


def setup_logging(log_filename: str) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log_path = LOGS_DIR / log_filename

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)