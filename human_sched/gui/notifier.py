"""Notification adapter that forwards scheduler notifications into the GUI event hub."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock, Timer
from uuid import uuid4

from human_sched.gui.events import EventHub
from human_sched.ports.notifications import NotificationEventType, NotificationPort


class EventingNotifier(NotificationPort):
    """Bridges scheduler notifications to in-process GUI events."""

    __slots__ = ("_event_hub", "_timers", "_lock")

    def __init__(self, event_hub: EventHub) -> None:
        self._event_hub = event_hub
        self._timers: dict[str, Timer] = {}
        self._lock = Lock()

    def schedule_notification(
        self,
        at: datetime,
        message: str,
        event_type: NotificationEventType,
    ) -> str:
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)

        notification_id = str(uuid4())
        delay = max(0.0, (at - datetime.now(timezone.utc)).total_seconds())

        timer = Timer(delay, self._fire_scheduled, args=(notification_id, message, event_type))
        timer.daemon = True

        with self._lock:
            self._timers[notification_id] = timer

        timer.start()
        return notification_id

    def cancel_notification(self, notification_id: str) -> None:
        with self._lock:
            timer = self._timers.pop(notification_id, None)
        if timer is not None:
            timer.cancel()

    def notify_immediately(self, message: str, event_type: NotificationEventType) -> None:
        self._event_hub.publish(
            event_type=event_type.value,
            message=message,
            source="runtime",
        )

    def _fire_scheduled(
        self,
        notification_id: str,
        message: str,
        event_type: NotificationEventType,
    ) -> None:
        with self._lock:
            self._timers.pop(notification_id, None)
        self.notify_immediately(message, event_type)
