"""
Processor and ProcessorSet, modeling a single cluster of CPUs.

In XNU, a processor_set (pset) owns a ClutchRoot hierarchy and an RT queue.
Each processor runs one thread at a time and participates in scheduling decisions.
"""

from __future__ import annotations

from enum import IntEnum, auto

from .thread import Thread, ThreadState
from .clutch_root import ClutchRoot
from .rt_queue import RTQueue


class ProcessorState(IntEnum):
    IDLE = 0
    DISPATCHING = 1
    RUNNING = 2


class Processor:
    """A single CPU core in the simulation."""

    __slots__ = (
        "processor_id",
        "state",
        "active_thread",
        "current_pri",
        "quantum_end",
        "first_timeslice",
        "starting_pri",
        # Stats
        "idle_time_us",
        "busy_time_us",
        "context_switches",
        "last_dispatch_time",
    )

    def __init__(self, processor_id: int) -> None:
        self.processor_id = processor_id
        self.state = ProcessorState.IDLE
        self.active_thread: Thread | None = None
        self.current_pri: int = -1
        self.quantum_end: int = 0
        self.first_timeslice: bool = False
        self.starting_pri: int = -1

        # Stats
        self.idle_time_us: int = 0
        self.busy_time_us: int = 0
        self.context_switches: int = 0
        self.last_dispatch_time: int = 0

    @property
    def is_idle(self) -> bool:
        return self.state == ProcessorState.IDLE or self.active_thread is None

    def __repr__(self) -> str:
        thread_str = self.active_thread.name if self.active_thread else "idle"
        return f"CPU{self.processor_id}({thread_str}, pri={self.current_pri})"


class ProcessorSet:
    """A set of processors sharing a ClutchRoot and RT queue."""

    __slots__ = (
        "pset_id",
        "processors",
        "rt_runq",
        "clutch_root",
        "processor_count",
    )

    def __init__(self, pset_id: int = 0, num_cpus: int = 4) -> None:
        self.pset_id = pset_id
        self.processors = [Processor(i) for i in range(num_cpus)]
        self.rt_runq = RTQueue()
        self.clutch_root = ClutchRoot(cluster_id=pset_id)
        self.processor_count = num_cpus

    def find_idle_processor(self) -> Processor | None:
        """Find an idle processor, if any."""
        for proc in self.processors:
            if proc.is_idle:
                return proc
        return None

    def find_lowest_priority_processor(self) -> Processor | None:
        """Find the processor running the lowest-priority thread."""
        lowest: Processor | None = None
        lowest_pri = 0x7FFFFFFF
        for proc in self.processors:
            if proc.active_thread is not None:
                if proc.current_pri < lowest_pri:
                    lowest_pri = proc.current_pri
                    lowest = proc
        return lowest

    def __repr__(self) -> str:
        idle = sum(1 for p in self.processors if p.is_idle)
        return (
            f"PSet(id={self.pset_id}, cpus={self.processor_count}, "
            f"idle={idle}, rt_count={self.rt_runq.count})"
        )
