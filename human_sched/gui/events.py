"""In-process event hub for GUI adapters and SSE clients."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from threading import RLock


@dataclass(frozen=True, slots=True)
class SchedulerEvent:
    """Serializable scheduler event emitted to GUI adapters."""

    event_id: int
    event_type: str
    message: str
    timestamp: datetime
    related_task_id: int | None = None
    source: str = "scheduler"


class EventHub:
    """Thread-safe pub/sub hub with bounded history and fan-out queues."""

    __slots__ = (
        "_events",
        "_subscribers",
        "_subscriber_queue_size",
        "_next_event_id",
        "_next_subscriber_id",
        "_dropped_event_count",
        "_lock",
    )

    def __init__(self, *, history_limit: int = 512, subscriber_queue_size: int = 256) -> None:
        self._events: deque[SchedulerEvent] = deque(maxlen=history_limit)
        self._subscribers: dict[int, Queue[SchedulerEvent]] = {}
        self._subscriber_queue_size = subscriber_queue_size
        self._next_event_id = 1
        self._next_subscriber_id = 1
        self._dropped_event_count = 0
        self._lock = RLock()

    def publish(
        self,
        *,
        event_type: str,
        message: str,
        related_task_id: int | None = None,
        source: str = "scheduler",
    ) -> SchedulerEvent:
        with self._lock:
            event = SchedulerEvent(
                event_id=self._next_event_id,
                event_type=event_type,
                message=message,
                timestamp=datetime.now(timezone.utc),
                related_task_id=related_task_id,
                source=source,
            )
            self._next_event_id += 1
            self._events.append(event)

            for queue in self._subscribers.values():
                try:
                    queue.put_nowait(event)
                except Full:
                    self._dropped_event_count += 1

            return event

    def list_recent(self, *, limit: int = 200) -> list[SchedulerEvent]:
        with self._lock:
            if limit <= 0:
                return []
            return list(self._events)[-limit:]

    def subscribe(self, *, after_event_id: int | None = None) -> int:
        with self._lock:
            subscriber_id = self._next_subscriber_id
            self._next_subscriber_id += 1
            queue: Queue[SchedulerEvent] = Queue(maxsize=self._subscriber_queue_size)

            backlog = self._events
            if after_event_id is not None:
                backlog = deque(
                    (event for event in self._events if event.event_id > after_event_id),
                    maxlen=len(self._events),
                )

            for event in backlog:
                try:
                    queue.put_nowait(event)
                except Full:
                    self._dropped_event_count += 1
                    break

            self._subscribers[subscriber_id] = queue
            return subscriber_id

    def unsubscribe(self, subscriber_id: int) -> None:
        with self._lock:
            self._subscribers.pop(subscriber_id, None)

    def next_event(
        self,
        subscriber_id: int,
        *,
        timeout_seconds: float | None = None,
    ) -> SchedulerEvent | None:
        with self._lock:
            queue = self._subscribers.get(subscriber_id)
        if queue is None:
            return None

        try:
            return queue.get(timeout=timeout_seconds)
        except Empty:
            return None

    @property
    def dropped_event_count(self) -> int:
        with self._lock:
            return self._dropped_event_count

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    @property
    def last_event(self) -> SchedulerEvent | None:
        with self._lock:
            if not self._events:
                return None
            return self._events[-1]
