"""
Discrete-event simulation event types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Any


class EventType(IntEnum):
    THREAD_WAKEUP = auto()
    THREAD_BLOCK = auto()
    QUANTUM_EXPIRE = auto()
    SCHED_TICK = auto()
    PREEMPTION_CHECK = auto()
    RT_DEADLINE = auto()
    RT_PERIOD_START = auto()
    SIMULATION_END = auto()


@dataclass(order=True)
class Event:
    """A simulation event, ordered by timestamp then by priority."""

    timestamp: int  # microseconds
    priority: int = field(compare=True, default=0)  # lower = higher priority
    event_type: EventType = field(compare=False, default=EventType.SIMULATION_END)
    thread_id: int = field(compare=False, default=-1)
    processor_id: int = field(compare=False, default=-1)
    data: dict[str, Any] = field(compare=False, default_factory=dict)
    _seq: int = field(compare=True, default=0)

    def __repr__(self) -> str:
        return (
            f"Event({self.event_type.name}, t={self.timestamp}, "
            f"thread={self.thread_id}, cpu={self.processor_id})"
        )


# Event priority ordering (lower = processed first at same timestamp)
EVENT_PRIORITY = {
    EventType.RT_DEADLINE: 0,
    EventType.THREAD_WAKEUP: 1,
    EventType.RT_PERIOD_START: 2,
    EventType.PREEMPTION_CHECK: 3,
    EventType.QUANTUM_EXPIRE: 4,
    EventType.THREAD_BLOCK: 5,
    EventType.SCHED_TICK: 6,
    EventType.SIMULATION_END: 99,
}
