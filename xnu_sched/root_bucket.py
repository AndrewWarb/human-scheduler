"""
ClutchRootBucket: per-QoS root bucket with EDF deadline, warp, and starvation avoidance.

Faithfully ports sched_clutch_root_bucket from sched_clutch.h:93-116
and the root bucket selection algorithm from sched_clutch.c:838-1037.
"""

from __future__ import annotations

from .constants import (
    ROOT_BUCKET_WCEL_US,
    ROOT_BUCKET_WARP_US,
    SCHED_CLUTCH_ROOT_BUCKET_WARP_UNUSED,
    SCHED_CLUTCH_INVALID_TIME_64,
    THREAD_QUANTUM_US,
    TH_BUCKET_SCHED_MAX,
    is_above_timeshare,
)
from .priority_queue import ClutchBucketRunqueue


class ClutchRootBucket:
    """Represents all threads across all thread groups at one QoS level.

    The root bucket is selected for execution using EDF (Earliest Deadline First)
    with warp and starvation avoidance mechanisms.
    """

    __slots__ = (
        "scrb_bucket",
        "scrb_bound",
        "scrb_starvation_avoidance",
        "scrb_starvation_ts",
        "scrb_deadline",
        "scrb_warp_remaining",
        "scrb_warped_deadline",
        "scrb_clutch_buckets",
    )

    def __init__(self, bucket: int, bound: bool = False) -> None:
        self.scrb_bucket = bucket
        self.scrb_bound = bound
        self.scrb_starvation_avoidance: bool = False
        self.scrb_starvation_ts: int = 0

        # EDF deadline
        self.scrb_deadline: int = 0

        # Warp: budget and deadline
        self.scrb_warp_remaining: int = ROOT_BUCKET_WARP_US[bucket]
        self.scrb_warped_deadline: int = SCHED_CLUTCH_ROOT_BUCKET_WARP_UNUSED

        # Clutch bucket runqueue (for unbound root buckets)
        self.scrb_clutch_buckets = ClutchBucketRunqueue()

    def deadline_calculate(self, timestamp: int) -> int:
        """Calculate EDF deadline for this root bucket.

        Ports sched_clutch_root_bucket_deadline_calculate() (sched_clutch.c:1050-1062).
        FIXPRI (Above UI) always returns 0 (earliest deadline).
        Timeshare buckets: current_time + WCEL.
        """
        if is_above_timeshare(self.scrb_bucket):
            return 0
        return timestamp + ROOT_BUCKET_WCEL_US[self.scrb_bucket]

    def deadline_update(self, timestamp: int) -> None:
        """Update the deadline when this bucket is selected.

        Ports sched_clutch_root_bucket_deadline_update() (sched_clutch.c:1071-1095).
        """
        if is_above_timeshare(self.scrb_bucket):
            return

        new_deadline = self.deadline_calculate(timestamp)
        self.scrb_deadline = new_deadline

    def reset_warp(self) -> None:
        """Reset warp budget to full when bucket is selected in natural EDF order."""
        self.scrb_warp_remaining = ROOT_BUCKET_WARP_US[self.scrb_bucket]
        self.scrb_warped_deadline = SCHED_CLUTCH_ROOT_BUCKET_WARP_UNUSED

    def on_empty(self, timestamp: int) -> None:
        """Handle root bucket becoming empty.

        Ports sched_clutch_root_bucket_empty() (sched_clutch.c:1141-1179).
        """
        if is_above_timeshare(self.scrb_bucket):
            return

        # Update warp remaining if warp was in use
        if self.scrb_warped_deadline != SCHED_CLUTCH_ROOT_BUCKET_WARP_UNUSED:
            if self.scrb_warped_deadline > timestamp:
                self.scrb_warp_remaining = self.scrb_warped_deadline - timestamp
            else:
                self.scrb_warp_remaining = 0

    def __repr__(self) -> str:
        from .constants import BUCKET_NAMES

        name = BUCKET_NAMES.get(self.scrb_bucket, "??")
        bound_str = "bound" if self.scrb_bound else "unbound"
        return f"RootBucket({name}, {bound_str}, deadline={self.scrb_deadline})"
