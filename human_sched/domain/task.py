"""Task domain entity wrapping a scheduler Thread."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from xnu_sched.thread import Thread, ThreadState

from .life_area import LifeArea
from .urgency import UrgencyTier


@dataclass(slots=True)
class Task:
    """Human task mapped to one scheduler thread."""

    title: str
    life_area: LifeArea
    urgency_tier: UrgencyTier
    thread: Thread
    notes: str = ""
    due_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def task_id(self) -> int:
        return self.thread.tid

    @property
    def state(self) -> ThreadState:
        return self.thread.state

    @property
    def is_completed(self) -> bool:
        return self.thread.state == ThreadState.TERMINATED
