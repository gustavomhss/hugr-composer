from __future__ import annotations
from typing import Any
import json
import time


async def publish_event(channel: str, event_name: str, payload: dict[str, Any], event_id: str | None=None) -> None:
    """Publish an SSE event to *channel*.

    Fan-out is handled by Redis pub/sub so clients connected to any
    worker receive the event.  The event is also written to the
    per-channel sorted-set replay buffer.

    Args:
        channel: Logical channel name (e.g. ``user:<uuid>``).
        event_name: SSE ``event:`` field value.
        payload: JSON-serializable event data.
        event_id: Optional explicit event id.  Auto-generated if omitted.

    Raises:
        ValueError: If the serialized payload exceeds ``MAX_PAYLOAD_BYTES``.
    """
    if event_id is None:
        event_id = f'{int(time.time() * 1000)}-{uuid4().hex[:8]}'
    body = json.dumps({'id': event_id, 'event': event_name, 'data': payload}, separators=(',', ':'), sort_keys=True)
    if len(body.encode('utf-8')) > MAX_PAYLOAD_BYTES:
        raise ValueError(f'SSE payload exceeds {MAX_PAYLOAD_BYTES} bytes')
    redis = await get_redis()
    try:
        score = float(event_id.split('-')[0])
    except (ValueError, IndexError):
        score = float(int(time.time() * 1000))
    pipe = redis.pipeline()
    pipe.publish(PUBSUB_CHANNEL.format(channel=channel), body)
    pipe.zadd(REPLAY_KEY.format(channel=channel), {body: score})
    pipe.zremrangebyrank(REPLAY_KEY.format(channel=channel), 0, -(_REPLAY_BUFFER_SIZE + 1))
    pipe.expire(REPLAY_KEY.format(channel=channel), _REPLAY_TTL)
    await pipe.execute()
