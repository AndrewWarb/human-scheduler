"""
RT (Real-Time) thread scheduling queue.

Ports the RT runqueue policy from XNU:
- primary ordering by RT priority (higher sched_pri first)
- deadline ordering within each RT priority band
- optional EDF override for a lower-priority RT thread when safe

Based on sched.h:281-293 and the RT scheduling paths in sched_prim.c.
"""

from __future__ import annotations

from .constants import BASEPRI_RTQUEUES, MAXPRI
from .thread import Thread


class RTQueue:
    """Realtime runqueue with XNU-like priority/deadline behavior."""

    __slots__ = (
        "_queues",
        "_count",
        "_earliest_deadline",
        "_constraint",
        "_ed_index",
        "_strict_priority",
        "_deadline_epsilon",
    )

    def __init__(self) -> None:
        nrtqs = (MAXPRI - BASEPRI_RTQUEUES) + 1
        self._queues: list[list[Thread]] = [[] for _ in range(nrtqs)]
        self._count: int = 0
        self._earliest_deadline: int = 0xFFFFFFFFFFFFFFFF
        self._constraint: int = 0xFFFFFFFF
        self._ed_index: int = -1
        self._strict_priority: bool = False
        self._deadline_epsilon: int = 100  # us

    @property
    def count(self) -> int:
        return self._count

    @property
    def strict_priority(self) -> bool:
        return self._strict_priority

    @property
    def deadline_epsilon(self) -> int:
        return self._deadline_epsilon

    def empty(self) -> bool:
        return self._count == 0

    def _to_index(self, pri: int) -> int:
        return pri - BASEPRI_RTQUEUES

    def _refresh_global_ed(self) -> None:
        earliest = 0xFFFFFFFFFFFFFFFF
        constraint = 0xFFFFFFFF
        ed_index = -1
        # Match XNU rt_runq_dequeue()/consistency walks: when deadlines tie,
        # keep the highest RT priority band as the earliest-deadline index.
        for i in range(len(self._queues) - 1, -1, -1):
            q = self._queues[i]
            if q and q[0].rt_deadline < earliest:
                earliest = q[0].rt_deadline
                constraint = q[0].rt_constraint
                ed_index = i
        self._earliest_deadline = earliest
        self._constraint = constraint
        self._ed_index = ed_index

    def _highest_pri_index(self) -> int:
        for i in range(len(self._queues) - 1, -1, -1):
            if self._queues[i]:
                return i
        return -1

    def highest_priority(self) -> int:
        """Return highest RT priority currently enqueued, or -1 when empty."""
        i = self._highest_pri_index()
        if i < 0:
            return -1
        return BASEPRI_RTQUEUES + i

    def peek_highest_priority(self) -> Thread | None:
        """Return the first thread at the highest RT priority."""
        i = self._highest_pri_index()
        if i < 0:
            return None
        q = self._queues[i]
        if not q:
            return None
        return q[0]

    def _choose_index_for_dequeue(self) -> int:
        hi_index = self._highest_pri_index()
        if hi_index < 0:
            return -1

        chosen = hi_index
        if (not self._strict_priority) and self._ed_index >= 0 and self._ed_index != hi_index:
            ed_thread = self._queues[self._ed_index][0]
            hi_thread = self._queues[hi_index][0]
            # Match sched_rt.c: allow EDF choice when it can still meet hi_thread constraint.
            if (
                ed_thread.rt_computation
                + hi_thread.rt_computation
                + self._deadline_epsilon
                < hi_thread.rt_constraint
            ):
                chosen = self._ed_index
        return chosen

    def enqueue(self, thread: Thread) -> bool:
        """Insert an RT thread ordered by deadline within its RT priority.

        Returns True when insertion suggests immediate preemption opportunity,
        matching rt_runq_enqueue() behavior (new head at that priority).
        """
        pri = thread.sched_pri
        assert BASEPRI_RTQUEUES <= pri <= MAXPRI
        idx = self._to_index(pri)
        q = self._queues[idx]

        inserted_head = False
        if not q:
            q.append(thread)
            inserted_head = True
        else:
            pos = len(q)
            for i, t in enumerate(q):
                if thread.rt_deadline < t.rt_deadline:
                    pos = i
                    break
            q.insert(pos, thread)
            inserted_head = pos == 0

        self._count += 1
        self._refresh_global_ed()
        return inserted_head

    def dequeue(self) -> Thread | None:
        """Remove and return the next RT thread per XNU runqueue policy."""
        idx = self._choose_index_for_dequeue()
        if idx < 0:
            return None
        q = self._queues[idx]
        thread = q.pop(0)
        self._count -= 1
        self._refresh_global_ed()
        return thread

    def peek(self) -> Thread | None:
        """Return the next RT thread per dequeue policy without removing it."""
        idx = self._choose_index_for_dequeue()
        if idx < 0:
            return None
        return self._queues[idx][0]

    def peek_deadline(self) -> int:
        """Return earliest RT deadline across all RT priorities."""
        return self._earliest_deadline

    def remove(self, thread: Thread) -> None:
        """Remove a specific thread from the queue."""
        pri = thread.sched_pri
        if not (BASEPRI_RTQUEUES <= pri <= MAXPRI):
            return
        idx = self._to_index(pri)
        q = self._queues[idx]
        for i, t in enumerate(q):
            if t is thread:
                q.pop(i)
                self._count -= 1
                self._refresh_global_ed()
                return

    def __len__(self) -> int:
        return self._count
