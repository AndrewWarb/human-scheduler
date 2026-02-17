"""
Priority queue implementations matching XNU kernel semantics.

XNU uses several priority queue variants:
- priority_queue_sched_max: max-priority queue (for thread selection)
- priority_queue_deadline_min: min-deadline queue (for EDF root buckets)
- priority_queue_sched_stable_max: stable max-priority with preempted-first semantics
- sched_clutch_bucket_runq: bitmap + per-priority circular queues
"""

from __future__ import annotations

import heapq
from collections import deque
from typing import TypeVar, Generic, Callable

from .constants import NRQS_MAX

T = TypeVar("T")


class PriorityQueueMax(Generic[T]):
    """Max-priority queue. Items with higher priority are dequeued first.

    Matches XNU's priority_queue_sched_max.
    Uses a min-heap with negated priorities.
    """

    __slots__ = ("_heap", "_counter", "_key")

    def __init__(self, key: Callable[[T], int] | None = None):
        self._heap: list[tuple[int, int, T]] = []
        self._counter: int = 0
        self._key = key

    def _pri(self, item: T) -> int:
        return self._key(item) if self._key else item  # type: ignore[return-value]

    def insert(self, item: T) -> None:
        pri = self._pri(item)
        self._counter += 1
        heapq.heappush(self._heap, (-pri, self._counter, item))

    def remove(self, item: T) -> None:
        # Mark-and-sweep: rebuild without the item
        self._heap = [(p, c, i) for p, c, i in self._heap if i is not item]
        heapq.heapify(self._heap)

    def peek_max(self) -> T | None:
        while self._heap:
            return self._heap[0][2]
        return None

    def pop_max(self) -> T | None:
        if self._heap:
            return heapq.heappop(self._heap)[2]
        return None

    def max_priority(self) -> int:
        if self._heap:
            return -self._heap[0][0]
        return -1

    def empty(self) -> bool:
        return len(self._heap) == 0

    def __len__(self) -> int:
        return len(self._heap)

    def __iter__(self):
        # Iterate in priority order (highest first) without modifying
        for _, _, item in sorted(self._heap):
            yield item

    def update_priority(self, item: T) -> None:
        """Re-insert item with its current priority."""
        self.remove(item)
        self.insert(item)


class PriorityQueueDeadlineMin(Generic[T]):
    """Min-deadline priority queue. Items with earliest deadline dequeued first.

    Matches XNU's priority_queue_deadline_min for root bucket EDF scheduling.
    """

    __slots__ = ("_heap", "_counter", "_deadline_fn")

    def __init__(self, deadline_fn: Callable[[T], int]):
        self._heap: list[tuple[int, int, T]] = []
        self._counter: int = 0
        self._deadline_fn = deadline_fn

    def insert(self, item: T) -> None:
        deadline = self._deadline_fn(item)
        self._counter += 1
        heapq.heappush(self._heap, (deadline, self._counter, item))

    def remove(self, item: T) -> None:
        self._heap = [(d, c, i) for d, c, i in self._heap if i is not item]
        heapq.heapify(self._heap)

    def peek_min(self) -> T | None:
        if self._heap:
            return self._heap[0][2]
        return None

    def min_deadline(self) -> int:
        if self._heap:
            return self._heap[0][0]
        return NRQS_MAX  # sentinel

    def pop_min(self) -> T | None:
        if self._heap:
            return heapq.heappop(self._heap)[2]
        return None

    def empty(self) -> bool:
        return len(self._heap) == 0

    def __len__(self) -> int:
        return len(self._heap)

    def update_deadline(self, item: T) -> None:
        """Re-insert item with its current deadline."""
        self.remove(item)
        self.insert(item)


class StablePriorityQueue(Generic[T]):
    """Max-priority queue with FIFO tiebreaking and preempted-first semantics.

    Matches XNU's priority_queue_sched_stable_max used for thread runqueues.

    Within the same priority level:
    - Preempted threads (HEADQ) go before non-preempted threads
    - Among same preemption status, FIFO order is maintained
    - Stamp-based ordering within the same priority level
    """

    __slots__ = ("_heap", "_counter", "_pri_fn")

    def __init__(self, pri_fn: Callable[[T], int]):
        self._heap: list[tuple[int, int, int, T]] = []
        self._counter: int = 0
        self._pri_fn = pri_fn

    def insert(self, item: T, preempted: bool = False, stamp: int = 0) -> None:
        pri = self._pri_fn(item)
        self._counter += 1
        # XNU stable runq key packs (sched_pri, preempted-bit):
        # key = (pri << 8) + modifier, where PREEMPTED modifier sorts higher.
        key = (pri << 8) + (1 if preempted else 0)
        # Within same key, XNU prefers:
        # - preempted entries: younger first (higher stamp)
        # - non-preempted entries: older first (lower stamp)
        stamp_key = -stamp if preempted else stamp
        # For equal stamp among preempted entries, preserve head-insert semantics:
        # newer insertion should win (like repeated enqueue_head on a runqueue).
        seq_key = -self._counter if preempted else self._counter
        heapq.heappush(self._heap, (-key, stamp_key, seq_key, item))

    def remove(self, item: T) -> None:
        self._heap = [(k, sk, sq, i) for k, sk, sq, i in self._heap if i is not item]
        heapq.heapify(self._heap)

    def peek_max(self) -> T | None:
        if self._heap:
            return self._heap[0][3]
        return None

    def pop_max(self) -> T | None:
        if self._heap:
            return heapq.heappop(self._heap)[3]
        return None

    def max_priority(self) -> int:
        if self._heap:
            # Drop the packed modifier bit.
            return (-self._heap[0][0]) >> 8
        return -1

    def empty(self) -> bool:
        return len(self._heap) == 0

    def __len__(self) -> int:
        return len(self._heap)

    def update_priority(self, item: T, preempted: bool = False, stamp: int = 0) -> None:
        self.remove(item)
        self.insert(item, preempted=preempted, stamp=stamp)

    def refresh_priorities(self) -> None:
        """Recompute packed keys from current item priorities.

        Preserves preempted/non-preempted modifier, timestamp ordering, and
        insertion-order tie-breakers.
        """
        refreshed: list[tuple[int, int, int, T]] = []
        for neg_key, stamp_key, seq_key, item in self._heap:
            packed = -neg_key
            preempted = bool(packed & 0x1)
            pri = self._pri_fn(item)
            new_packed = (pri << 8) + (1 if preempted else 0)
            refreshed.append((-new_packed, stamp_key, seq_key, item))
        self._heap = refreshed
        heapq.heapify(self._heap)


class ClutchBucketRunqueue:
    """Bitmap + per-priority circular queues for clutch buckets.

    Faithfully ports sched_clutch_bucket_runq from sched_clutch.h:63-68.
    Uses a bitmap to track which priority levels have runnable clutch buckets,
    and circular queues at each level for round-robin within a priority.
    """

    __slots__ = ("_highq", "_count", "_bitmap", "_queues")

    def __init__(self) -> None:
        self._highq: int = -1
        self._count: int = 0
        self._bitmap: int = 0  # bit i set if queue[i] is non-empty
        self._queues: list[deque] = [deque() for _ in range(NRQS_MAX)]

    @property
    def highq(self) -> int:
        return self._highq

    @property
    def count(self) -> int:
        return self._count

    def empty(self) -> bool:
        return self._count == 0

    def enqueue(self, item: T, priority: int, head: bool = False) -> None:
        """Insert a clutch bucket at the given priority level."""
        assert 0 <= priority < NRQS_MAX
        if head:
            self._queues[priority].appendleft(item)
        else:
            self._queues[priority].append(item)
        self._bitmap |= (1 << priority)
        self._count += 1
        if priority > self._highq:
            self._highq = priority

    def dequeue(self, item: T, priority: int) -> None:
        """Remove a specific clutch bucket from its priority level."""
        q = self._queues[priority]
        q.remove(item)
        self._count -= 1
        if not q:
            self._bitmap &= ~(1 << priority)
            if priority == self._highq:
                self._highq = self._find_highest()

    def peek_highest(self) -> T | None:
        """Return the first item at the highest priority level."""
        if self._highq < 0:
            return None
        q = self._queues[self._highq]
        return q[0] if q else None

    def highest_priority(self) -> int:
        return self._highq

    def rotate_at(self, priority: int) -> None:
        """Round-robin: rotate the queue at the given priority (move head to tail)."""
        q = self._queues[priority]
        if len(q) > 1:
            q.append(q.popleft())

    def items_at(self, priority: int) -> deque:
        return self._queues[priority]

    def all_items(self):
        """Iterate all items, highest priority first."""
        pri = self._highq
        while pri >= 0:
            for item in self._queues[pri]:
                yield item
            pri = self._next_lower(pri)

    def _find_highest(self) -> int:
        """Find highest set bit in bitmap."""
        if self._bitmap == 0:
            return -1
        return self._bitmap.bit_length() - 1

    def _next_lower(self, pri: int) -> int:
        """Find next lower priority with items."""
        mask = self._bitmap & ((1 << pri) - 1)
        if mask == 0:
            return -1
        return mask.bit_length() - 1

    def move_item(self, item: T, old_pri: int, new_pri: int, head: bool = False) -> None:
        """Move a clutch bucket from one priority level to another."""
        self.dequeue(item, old_pri)
        self.enqueue(item, new_pri, head=head)
