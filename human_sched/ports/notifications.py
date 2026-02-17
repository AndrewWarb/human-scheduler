"""Notification port abstractions for human scheduler adapters."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Protocol


class NotificationEventType(str, Enum):
    """High-level scheduler events exposed to notification adapters."""

    QUANTUM_EXPIRE = "quantum_expire"
    SCHED_TICK = "sched_tick"
    PREEMPTION = "preemption"
    INFO = "info"


class NotificationPort(Protocol):
    """Port for delivering immediate and scheduled notifications."""

    def schedule_notification(
        self,
        at: datetime,
        message: str,
        event_type: NotificationEventType,
    ) -> str:
        """Schedule a future notification and return a cancellable id."""

    def cancel_notification(self, notification_id: str) -> None:
        """Cancel a previously scheduled notification."""

    def notify_immediately(self, message: str, event_type: NotificationEventType) -> None:
        """Push an immediate notification for a scheduler event."""
