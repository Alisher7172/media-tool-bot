import json
from dataclasses import asdict, dataclass
from typing import Any

import redis

from app.config import settings


@dataclass
class MediaJobPayload:
    job_id: int
    chat_id: int
    telegram_user_id: int
    username: str | None
    url: str
    title: str
    media_type: str
    selected_value: str
    attempt: int = 0


def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )


def enqueue_media_job(payload: MediaJobPayload) -> None:
    client = get_redis_client()
    client.rpush(settings.QUEUE_NAME, json.dumps(asdict(payload)))


def requeue_media_job(payload: dict[str, Any]) -> None:
    client = get_redis_client()
    client.rpush(settings.QUEUE_NAME, json.dumps(payload))


def move_to_dead_letter_queue(payload: dict[str, Any], reason: str) -> None:
    client = get_redis_client()

    payload["dead_letter_reason"] = reason

    client.rpush(
        settings.DEAD_LETTER_QUEUE_NAME,
        json.dumps(payload),
    )


def dequeue_media_job(block_timeout_seconds: int = 5) -> dict[str, Any] | None:
    client = get_redis_client()

    result = client.blpop(
        [settings.QUEUE_NAME],
        timeout=block_timeout_seconds,
    )

    if result is None:
        return None

    _queue_name, raw_payload = result
    return json.loads(raw_payload)


def get_queue_length() -> int:
    client = get_redis_client()
    return int(client.llen(settings.QUEUE_NAME))


def get_dead_letter_queue_length() -> int:
    client = get_redis_client()
    return int(client.llen(settings.DEAD_LETTER_QUEUE_NAME))


def get_job_position(job_id: int) -> int | None:
    client = get_redis_client()
    raw_items = client.lrange(settings.QUEUE_NAME, 0, -1)

    for index, raw_item in enumerate(raw_items, start=1):
        try:
            payload = json.loads(raw_item)
        except json.JSONDecodeError:
            continue

        if int(payload.get("job_id", -1)) == job_id:
            return index

    return None