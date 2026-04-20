from __future__ import annotations
import json


def format_event(event: SSEEvent) -> bytes:
    """Serialize an SSEEvent to the text/event-stream wire format.

    Args:
        event: The SSEEvent to serialize.

    Returns:
        UTF-8 encoded bytes ready to stream to the client.

    Raises:
        ValueError: If ``event_id`` or ``event_name`` is empty.
    """
    if not event.event_id:
        raise ValueError('event_id must be non-empty')
    if not event.event_name:
        raise ValueError('event_name must be non-empty')
    lines: list[str] = [f'id: {event.event_id}', f'event: {event.event_name}']
    if event.retry_ms is not None:
        lines.append(f'retry: {event.retry_ms}')
    data_json = json.dumps(event.payload, separators=(',', ':'), ensure_ascii=False)
    for data_line in data_json.splitlines() or ['']:
        lines.append(f'data: {data_line}')
    lines.append('')
    return ('\n'.join(lines) + '\n').encode('utf-8')
