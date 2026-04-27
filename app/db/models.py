from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    telegram_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chat_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    url: Mapped[str] = mapped_column(Text, nullable=False)
    media_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    selected_quality: Mapped[str | None] = mapped_column(String(50), nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    queued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)