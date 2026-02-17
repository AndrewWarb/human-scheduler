"""Terminal notification adapter using timer threads + stdout/bell."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock, Timer
from uuid import uuid4

from human_sched.ports.notifications import NotificationEventType, NotificationPort


class TerminalNotifier(NotificationPort):
    """Simple notification adapter for local terminal usage."""

    __slots__ = ("_enable_bell", "_timers", "_lock")

    def __init__(self, enable_bell: bool = False) -> None:
        self._enable_bell = enable_bell
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
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"[{now}] [{event_type.value}] {message}")
        if self._enable_bell:
            print("\a", end="")

    def _fire_scheduled(
        self,
        notification_id: str,
        message: str,
        event_type: NotificationEventType,
    ) -> None:
        with self._lock:
            self._timers.pop(notification_id, None)
        self.notify_immediately(message, event_type)
