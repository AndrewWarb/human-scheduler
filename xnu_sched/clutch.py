"""
Clutch hierarchy data structures, faithfully ported from:
  - osfmk/kern/sched_clutch.h:186-324
  - osfmk/kern/sched_clutch.c:1390-1978, 2560-2710

Three-level hierarchy (bottom to top):
  SchedClutchBucket       - per thread_group, per QoS, per cluster
  SchedClutchBucketGroup  - per thread_group, per QoS (cross-cluster)
  SchedClutch             - per thread_group
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .constants import (
    TH_BUCKET_SCHED_MAX,
    SCHED_CLUTCH_BUCKET_GROUP_INTERACTIVE_PRI_DEFAULT,
    SCHED_CLUTCH_BUCKET_GROUP_ADJUST_THRESHOLD_US,
    SCHED_CLUTCH_BUCKET_GROUP_ADJUST_RATIO,
    SCHED_CLUTCH_BUCKET_GROUP_BLOCKED_TS_INVALID,
    SCHED_CLUTCH_BUCKET_GROUP_PENDING_INVALID,
    SCHED_LOAD_SHIFTS,
    SCHED_FIXED_SHIFT,
    SCHED_PRI_SHIFT_MAX,
    NRQS,
    THREAD_QUANTUM_US,
    SCHED_CLUTCH_BUCKET_GROUP_PENDING_DELTA_US,
    SCHED_CLUTCH_INVALID_TIME_32,
    is_above_timeshare,
)
from .priority_queue import PriorityQueueMax, StablePriorityQueue
from .thread import Thread, ThreadGroup

if TYPE_CHECKING:
    from .clutch_root import ClutchRoot


class SchedClutchBucketGroup:
    """Per thread_group, per QoS bucket group (cross-cluster).

    Maintains timesharing properties, CPU usage tracking, and interactivity scoring.
    Ports sched_clutch_bucket_group from sched_clutch.h:276-298.
    """

    __slots__ = (
        "scbg_bucket",
        "scbg_clutch",
        "scbg_timeshare_tick",
        "scbg_pri_shift",
        # CPU data: (cpu_used, cpu_blocked) in microseconds
        "scbg_cpu_used",
        "scbg_cpu_blocked",
        # Blocked data: (run_count, blocked_timestamp)
        "scbg_blocked_count",
        "scbg_blocked_ts",
        # Pending data: (thread_count, pending_timestamp)
        "scbg_pending_count",
        "scbg_pending_ts",
        # Interactivity: (score, timestamp)
        "scbg_interactivity_score",
        "scbg_interactivity_ts",
        # Per-cluster clutch buckets (single cluster for our sim)
        "scbg_clutch_buckets",
    )

    def __init__(self, clutch: SchedClutch, bucket: int) -> None:
        self.scbg_bucket = bucket
        self.scbg_clutch = clutch
        self.scbg_timeshare_tick: int = 0
        self.scbg_pri_shift: int = 127  # INT8_MAX (no decay initially)

        # CPU data: initialized with threshold blocked time for initial interactivity
        # (sched_clutch.c:1415)
        self.scbg_cpu_used: int = 0
        self.scbg_cpu_blocked: int = SCHED_CLUTCH_BUCKET_GROUP_ADJUST_THRESHOLD_US

        # Blocked data (run_count, timestamp)
        self.scbg_blocked_count: int = 0
        self.scbg_blocked_ts: int = SCHED_CLUTCH_BUCKET_GROUP_BLOCKED_TS_INVALID

        # Pending data
        self.scbg_pending_count: int = 0
        self.scbg_pending_ts: int = SCHED_CLUTCH_BUCKET_GROUP_PENDING_INVALID

        # Interactivity: start at interactive_pri * 2 (sched_clutch.c:1413)
        self.scbg_interactivity_score: int = (
            SCHED_CLUTCH_BUCKET_GROUP_INTERACTIVE_PRI_DEFAULT * 2
        )
        self.scbg_interactivity_ts: int = 0

        # Single-cluster: one clutch bucket per group
        self.scbg_clutch_buckets: list[SchedClutchBucket] = []

    def init_clutch_bucket(self, cluster_id: int = 0) -> SchedClutchBucket:
        """Create a clutch bucket for a cluster."""
        cb = SchedClutchBucket(self, self.scbg_bucket)
        if len(self.scbg_clutch_buckets) <= cluster_id:
            self.scbg_clutch_buckets.extend(
                [None] * (cluster_id + 1 - len(self.scbg_clutch_buckets))  # type: ignore[list-item]
            )
        self.scbg_clutch_buckets[cluster_id] = cb
        return cb

    # ------------------------------------------------------------------
    # Run count management (sched_clutch.c:2646-2690)
    # ------------------------------------------------------------------
    def run_count_inc(self, timestamp: int) -> int:
        """Increment runnable/running thread count. Returns new count.

        Ports sched_clutch_bucket_group_run_count_inc().
        """
        old_count = self.scbg_blocked_count
        self.scbg_blocked_count += 1

        if old_count == 0:
            # Transitioning from all-blocked to having a runnable thread
            # Account blocked time
            old_ts = self.scbg_blocked_ts
            self.scbg_blocked_ts = SCHED_CLUTCH_BUCKET_GROUP_BLOCKED_TS_INVALID
            if old_ts != SCHED_CLUTCH_BUCKET_GROUP_BLOCKED_TS_INVALID:
                if timestamp > old_ts:
                    blocked_time = timestamp - old_ts
                    blocked_time = min(
                        blocked_time, SCHED_CLUTCH_BUCKET_GROUP_ADJUST_THRESHOLD_US
                    )
                    self.scbg_cpu_blocked += blocked_time

        return self.scbg_blocked_count

    def run_count_dec(self, timestamp: int) -> int:
        """Decrement runnable/running thread count. Returns new count.

        Ports sched_clutch_bucket_group_run_count_dec().
        """
        self.scbg_blocked_count -= 1

        if self.scbg_blocked_count == 0:
            # All threads now blocked: record blocked timestamp
            self.scbg_blocked_ts = timestamp

        return self.scbg_blocked_count

    # ------------------------------------------------------------------
    # Thread count (pending data) management
    # ------------------------------------------------------------------
    def thr_count_inc(self, timestamp: int) -> None:
        """Track thread insertion for pending-based interactivity aging."""
        self.scbg_pending_count += 1
        if self.scbg_pending_ts == SCHED_CLUTCH_BUCKET_GROUP_PENDING_INVALID:
            self.scbg_pending_ts = timestamp

    def thr_count_dec(self, timestamp: int) -> None:
        self.scbg_pending_count -= 1
        if self.scbg_pending_count == 0:
            self.scbg_pending_ts = SCHED_CLUTCH_BUCKET_GROUP_PENDING_INVALID
        else:
            # Match non-Edge Clutch behavior: refresh pending timestamp while still pending.
            self.scbg_pending_ts = timestamp

    # ------------------------------------------------------------------
    # CPU usage update (sched_clutch.c:1907-1918)
    # ------------------------------------------------------------------
    def cpu_usage_update(self, delta: int) -> None:
        """Add CPU usage time for this bucket group.

        Ports sched_clutch_bucket_group_cpu_usage_update().
        """
        if is_above_timeshare(self.scbg_bucket):
            return
        delta = min(delta, SCHED_CLUTCH_BUCKET_GROUP_ADJUST_THRESHOLD_US)
        self.scbg_cpu_used += delta

    # ------------------------------------------------------------------
    # CPU data aging (sched_clutch.c:1953-1978)
    # ------------------------------------------------------------------
    def cpu_adjust(self, pending_intervals: int) -> None:
        """Scale CPU usage/blocked data and age out CPU usage.

        Ports sched_clutch_bucket_group_cpu_adjust().
        """
        cpu_used = self.scbg_cpu_used
        cpu_blocked = self.scbg_cpu_blocked

        if pending_intervals == 0 and (
            cpu_used + cpu_blocked
        ) < SCHED_CLUTCH_BUCKET_GROUP_ADJUST_THRESHOLD_US:
            return

        if (
            cpu_used + cpu_blocked
        ) >= SCHED_CLUTCH_BUCKET_GROUP_ADJUST_THRESHOLD_US:
            cpu_used //= SCHED_CLUTCH_BUCKET_GROUP_ADJUST_RATIO
            cpu_blocked //= SCHED_CLUTCH_BUCKET_GROUP_ADJUST_RATIO

        cpu_used = self._cpu_pending_adjust(cpu_used, cpu_blocked, pending_intervals)
        self.scbg_cpu_used = cpu_used
        self.scbg_cpu_blocked = cpu_blocked

    @staticmethod
    def _cpu_pending_adjust(
        cpu_used: int, cpu_blocked: int, pending_intervals: int
    ) -> int:
        """Calculate adjusted CPU usage based on pending intervals.

        Ports sched_clutch_bucket_group_cpu_pending_adjust() (sched_clutch.c:1926-1941).
        """
        if pending_intervals == 0:
            return cpu_used

        interactive_pri = SCHED_CLUTCH_BUCKET_GROUP_INTERACTIVE_PRI_DEFAULT

        if cpu_blocked < cpu_used:
            # Non-interactive case
            numerator = interactive_pri * cpu_blocked * cpu_used
            denominator = (interactive_pri * cpu_blocked) + (
                cpu_used * pending_intervals
            )
            if denominator == 0:
                return 0
            return numerator // denominator
        else:
            # Interactive case
            if interactive_pri == 0:
                return cpu_used
            adjust_factor = (cpu_blocked * pending_intervals) // interactive_pri
            return max(0, cpu_used - adjust_factor)

    # ------------------------------------------------------------------
    # Interactivity scoring (sched_clutch.c:1688-1713)
    # ------------------------------------------------------------------
    def interactivity_from_cpu_data(self) -> int:
        """Calculate interactivity score from CPU usage data.

        Ports sched_clutch_interactivity_from_cpu_data().
        Score range: [0, 16] where 8 is neutral, >8 is interactive, <8 is CPU-bound.
        """
        cpu_used = self.scbg_cpu_used
        cpu_blocked = self.scbg_cpu_blocked
        interactive_pri = SCHED_CLUTCH_BUCKET_GROUP_INTERACTIVE_PRI_DEFAULT

        if cpu_blocked == 0 and cpu_used == 0:
            return self.scbg_interactivity_score

        if cpu_blocked > cpu_used:
            # Interactive bucket
            score = interactive_pri + (
                (interactive_pri * (cpu_blocked - cpu_used)) // cpu_blocked
            )
        else:
            # Non-interactive bucket
            if cpu_used == 0:
                return interactive_pri
            score = (interactive_pri * cpu_blocked) // cpu_used

        return score

    # ------------------------------------------------------------------
    # Interactivity score with pending ageout (sched_clutch.c:2592-2632)
    # Non-Edge variant (simpler, no atomics needed)
    # ------------------------------------------------------------------
    def interactivity_score_calculate(
        self, timestamp: int, global_bucket_load: int = 0
    ) -> int:
        """Calculate and update interactivity score.

        Ports sched_clutch_bucket_group_interactivity_score_calculate() (non-Edge).
        """
        if is_above_timeshare(self.scbg_bucket):
            return self.scbg_interactivity_score

        # Pending ageout
        pending_intervals = self._pending_ageout(timestamp, global_bucket_load)
        # Adjust CPU stats
        self.cpu_adjust(pending_intervals)
        # Calculate score
        score = self.interactivity_from_cpu_data()

        # Write back (non-Edge path: sched_clutch.c:2627-2631)
        if timestamp > self.scbg_interactivity_ts:
            self.scbg_interactivity_score = score
            self.scbg_interactivity_ts = timestamp

        return self.scbg_interactivity_score

    def _pending_ageout(self, timestamp: int, global_bucket_load: int) -> int:
        """Calculate pending ageout intervals.

        Simplified port of sched_clutch_bucket_group_pending_ageout() (sched_clutch.c:2561-2588).
        """
        old_pending_ts = self.scbg_pending_ts
        if (
            old_pending_ts >= timestamp
            or old_pending_ts == SCHED_CLUTCH_BUCKET_GROUP_PENDING_INVALID
            or global_bucket_load == 0
        ):
            return 0

        pending_delta = timestamp - old_pending_ts
        bucket = self.scbg_bucket
        interactivity_delta = (
            SCHED_CLUTCH_BUCKET_GROUP_PENDING_DELTA_US[bucket]
            + global_bucket_load * THREAD_QUANTUM_US[bucket]
        )
        if interactivity_delta == 0 or pending_delta < interactivity_delta:
            return 0

        cpu_usage_shift = pending_delta // interactivity_delta
        self.scbg_pending_ts = old_pending_ts + (
            cpu_usage_shift * interactivity_delta
        )
        return cpu_usage_shift

    # ------------------------------------------------------------------
    # Pri shift update (sched_clutch.c:2057-2083)
    # ------------------------------------------------------------------
    def pri_shift_update(self, current_tick: int, processor_count: int) -> None:
        """Update priority shift for timeshare decay.

        Ports sched_clutch_bucket_group_pri_shift_update().
        """
        if is_above_timeshare(self.scbg_bucket):
            return

        if self.scbg_timeshare_tick < current_tick:
            self.scbg_timeshare_tick = current_tick

            # NCPU-wide workloads should not experience decay
            run_count = max(0, self.scbg_blocked_count - 1)
            if processor_count > 0:
                load = run_count // processor_count
            else:
                load = run_count
            load = min(load, NRQS - 1)

            pri_shift = SCHED_FIXED_SHIFT - SCHED_LOAD_SHIFTS[load]
            if pri_shift > SCHED_PRI_SHIFT_MAX:
                pri_shift = 127  # INT8_MAX: effectively no decay
            self.scbg_pri_shift = pri_shift


class SchedClutchBucket:
    """Per thread_group, per QoS, per cluster clutch bucket.

    Ports sched_clutch_bucket from sched_clutch.h:220-252.
    Contains the actual thread runqueue.
    """

    __slots__ = (
        "scb_bucket",
        "scb_priority",
        "scb_thr_count",
        "scb_group",
        "scb_root",
        "scb_thread_runq",
        "scb_clutchpri_prioq",
        "scb_timeshare_threads",
    )

    def __init__(self, group: SchedClutchBucketGroup, bucket: int) -> None:
        self.scb_bucket = bucket
        self.scb_priority: int = 0
        self.scb_thr_count: int = 0
        self.scb_group = group
        self.scb_root: ClutchRoot | None = None

        # Thread runqueue: stable max-priority queue by sched_pri
        self.scb_thread_runq: StablePriorityQueue[Thread] = StablePriorityQueue(
            pri_fn=lambda t: t.sched_pri
        )
        # Clutchpri queue: max-priority queue by base/promoted pri
        self.scb_clutchpri_prioq: PriorityQueueMax[Thread] = PriorityQueueMax(
            key=lambda t: t.sched_pri if t.sched_pri_promoted else t.base_pri
        )
        # Timeshare thread list (for sched_tick operations)
        self.scb_timeshare_threads: list[Thread] = []

    def base_pri(self) -> int:
        """Calculate base priority of the clutch bucket.

        Ports sched_clutch_bucket_base_pri() (sched_clutch.c:1665-1681).
        Returns max of highest promoted/base pri among threads.
        """
        if self.scb_clutchpri_prioq.empty():
            return 0
        return self.scb_clutchpri_prioq.max_priority()

    def pri_calculate(self, timestamp: int, global_bucket_load: int = 0) -> int:
        """Calculate clutch bucket priority = base_pri + interactivity_score.

        Ports sched_clutch_bucket_pri_calculate() (sched_clutch.c:1723-1743).
        """
        if self.scb_thr_count == 0:
            return 0

        base = self.base_pri()
        interactive_score = self.scb_group.interactivity_score_calculate(
            timestamp, global_bucket_load
        )
        return min(base + interactive_score, 255)

    def __repr__(self) -> str:
        tg = self.scb_group.scbg_clutch
        from .constants import BUCKET_NAMES

        bucket_name = BUCKET_NAMES.get(self.scb_bucket, "??")
        return (
            f"CB({tg.sc_tg.name}/{bucket_name}, "
            f"pri={self.scb_priority}, threads={self.scb_thr_count})"
        )

    def __getstate__(self) -> dict:
        return {slot: getattr(self, slot) for slot in self.__slots__}

    def __setstate__(self, state: dict) -> None:
        for slot in self.__slots__:
            setattr(self, slot, state.get(slot))
        self.scb_thread_runq._pri_fn = lambda t: t.sched_pri
        self.scb_clutchpri_prioq._key = (
            lambda t: t.sched_pri if t.sched_pri_promoted else t.base_pri
        )


class SchedClutch:
    """Per thread_group clutch. Top-level container for the hierarchy.

    Ports sched_clutch from sched_clutch.h:308-324.
    """

    __slots__ = ("sc_tg", "sc_thr_count", "sc_clutch_groups")

    def __init__(self, tg: ThreadGroup, num_clusters: int = 1) -> None:
        self.sc_tg = tg
        self.sc_thr_count: int = 0

        # Initialize all bucket groups (sched_clutch.c:1438-1443)
        self.sc_clutch_groups: list[SchedClutchBucketGroup] = []
        for bucket in range(TH_BUCKET_SCHED_MAX):
            group = SchedClutchBucketGroup(self, bucket)
            for cluster_id in range(num_clusters):
                group.init_clutch_bucket(cluster_id)
            self.sc_clutch_groups.append(group)

        # Link back
        tg.sched_clutch = self

    def bucket_for_thread(self, thread: Thread, cluster_id: int = 0) -> SchedClutchBucket:
        """Get the clutch bucket for a thread.

        Ports sched_clutch_bucket_for_thread() (sched_clutch.c:2692-2705).
        """
        group = self.sc_clutch_groups[thread.th_sched_bucket]
        return group.scbg_clutch_buckets[cluster_id]

    def bucket_group_for_thread(self, thread: Thread) -> SchedClutchBucketGroup:
        """Get the bucket group for a thread."""
        return self.sc_clutch_groups[thread.th_sched_bucket]

    def __repr__(self) -> str:
        return f"SchedClutch({self.sc_tg.name}, threads={self.sc_thr_count})"
