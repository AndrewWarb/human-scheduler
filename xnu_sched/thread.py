"""
Thread and ThreadGroup, ported from XNU's thread structure and
sched_clutch_thread_bucket_map() (sched_clutch.c:378-399).
"""

from __future__ import annotations

from enum import IntEnum, auto
from typing import TYPE_CHECKING

from .constants import (
    TH_MODE_REALTIME,
    TH_MODE_FIXED,
    TH_MODE_TIMESHARE,
    RT_DEADLINE_NONE,
    TH_BUCKET_FIXPRI,
    TH_BUCKET_SHARE_FG,
    TH_BUCKET_SHARE_IN,
    TH_BUCKET_SHARE_DF,
    TH_BUCKET_SHARE_UT,
    TH_BUCKET_SHARE_BG,
    TH_BUCKET_SCHED_MAX,
    BASEPRI_FOREGROUND,
    BASEPRI_RTQUEUES,
    BASEPRI_USER_INITIATED,
    BASEPRI_DEFAULT,
    BASEPRI_UTILITY,
    MAXPRI_THROTTLE,
    THREAD_QUANTUM_US,
    MINPRI,
    MAXPRI,
)

if TYPE_CHECKING:
    from .clutch import SchedClutch


class ThreadState(IntEnum):
    RUNNABLE = auto()
    RUNNING = auto()
    WAITING = auto()   # blocked / sleeping
    TERMINATED = auto()


_next_tid: int = 0


def _alloc_tid() -> int:
    global _next_tid
    tid = _next_tid
    _next_tid += 1
    return tid


class ThreadGroup:
    """Represents a macOS thread group (typically one per app).

    Each ThreadGroup owns a SchedClutch that manages its bucket hierarchy.
    """

    __slots__ = ("name", "tg_id", "sched_clutch")

    _next_id: int = 0

    def __init__(self, name: str) -> None:
        self.name = name
        self.tg_id = ThreadGroup._next_id
        ThreadGroup._next_id += 1
        self.sched_clutch: SchedClutch | None = None

    def __repr__(self) -> str:
        return f"TG({self.name}, id={self.tg_id})"


class Thread:
    """Represents a kernel thread with scheduling state.

    Faithfully models the scheduling-relevant fields from XNU's thread struct.
    """

    __slots__ = (
        "tid",  # Unique thread id assigned by the simulator.
        "name",  # Human-readable name used in traces and stats output.
        "thread_group",  # Owning ThreadGroup (application-like scheduling group).
        "sched_mode",  # Scheduling class: realtime, fixed, or timeshare.
        "base_pri",  # Base priority assigned at creation.
        "sched_pri",  # Current scheduling priority used for runqueue ordering.
        "max_priority",  # Upper clamp for dynamic scheduling priority.
        "th_sched_bucket",  # Clutch QoS bucket derived from mode and priority.
        "cpu_usage",  # Accumulated CPU usage used for stats/aging behavior.
        "sched_usage",  # Decay-specific usage used by sched_pri computation.
        "sched_stamp",  # Last scheduler tick when usage aging was applied.
        "sched_time_save",  # Reserved parity field; currently not used in decisions.
        "cpu_delta",  # CPU usage accumulated since the last aging pass.
        "pri_shift",  # Last effective priority-shift used for sched_usage charging.
        "quantum_remaining",  # Remaining timeslice budget in microseconds.
        "first_timeslice",  # True while running the thread's first quantum slice.
        "rt_period",  # RT period parameter for periodic realtime workloads.
        "rt_computation",  # RT computation budget used by deadline safety checks.
        "rt_constraint",  # RT constraint/deadline window for the period.
        "rt_deadline",  # Absolute deadline timestamp for the current RT period.
        "state",  # Execution state: WAITING, RUNNABLE, RUNNING, or TERMINATED.
        "last_run_time",  # Timestamp of last run/block transition.
        "last_made_runnable_time",  # Timestamp when thread most recently became runnable.
        "computation_epoch",  # Timestamp when current running segment started.
        "promoted_pri",  # Temporary boosted priority (e.g., lock-related promotion).
        "sched_pri_promoted",  # Whether promoted_pri should override base scheduling pri.
        "bound_processor",  # Optional CPU binding; None means unbound Clutch thread.
        "total_cpu_us",  # Total CPU runtime accumulated across the simulation.
        "total_wait_us",  # Total runnable-to-dispatch wait time accumulated.
        "context_switches",  # Number of context switches involving this thread.
        "preemption_count",  # Number of times this thread was preempted.
    )

    def __init__(
        self,
        thread_group: ThreadGroup,
        sched_mode: int = TH_MODE_TIMESHARE,
        base_pri: int = BASEPRI_DEFAULT,
        name: str = "",
        # RT params (only for TH_MODE_REALTIME)
        rt_period: int = 0,
        rt_computation: int = 0,
        rt_constraint: int = 0,
    ) -> None:
        self.tid = _alloc_tid()
        self.name = name or f"thread-{self.tid}"
        self.thread_group = thread_group
        self.sched_mode = sched_mode
        if sched_mode == TH_MODE_REALTIME and base_pri < BASEPRI_RTQUEUES:
            base_pri = BASEPRI_RTQUEUES
        self.base_pri = base_pri
        self.sched_pri = base_pri
        self.max_priority = MAXPRI if sched_mode == TH_MODE_REALTIME else base_pri

        # Map to scheduling bucket
        self.th_sched_bucket = thread_bucket_map(sched_mode, base_pri)

        # CPU accounting for timeshare decay
        self.cpu_usage: int = 0
        self.sched_usage: int = 0
        self.sched_stamp: int = 0
        self.sched_time_save: int = 0
        self.cpu_delta: int = 0
        self.pri_shift: int = 127  # INT8_MAX: no contention decay initially

        # RT
        self.rt_period = rt_period
        self.rt_computation = rt_computation
        self.rt_constraint = rt_constraint
        self.rt_deadline: int = RT_DEADLINE_NONE

        # Quantum
        self.quantum_remaining: int = self._initial_quantum()
        self.first_timeslice: bool = True

        # State
        self.state = ThreadState.WAITING
        self.last_run_time: int = 0
        self.last_made_runnable_time: int = 0
        self.computation_epoch: int = 0

        # Promotion (e.g. turnstile / mutex)
        self.promoted_pri: int = 0
        self.sched_pri_promoted: bool = False

        # Binding
        self.bound_processor = None

        # Stats
        self.total_cpu_us: int = 0
        self.total_wait_us: int = 0
        self.context_switches: int = 0
        self.preemption_count: int = 0

    @property
    def is_realtime(self) -> bool:
        return self.sched_mode == TH_MODE_REALTIME

    @property
    def is_timeshare(self) -> bool:
        return self.sched_mode == TH_MODE_TIMESHARE

    @property
    def effective_priority(self) -> int:
        """The priority used for scheduling decisions."""
        if self.sched_pri_promoted:
            return max(self.sched_pri, self.promoted_pri)
        return self.sched_pri

    def _initial_quantum(self) -> int:
        if self.is_realtime and self.rt_computation > 0:
            # XNU thread_quantum_init(): realtime quantum uses rt_computation.
            return self.rt_computation
        return THREAD_QUANTUM_US[self.th_sched_bucket]

    def reset_quantum(self) -> None:
        """Reset thread's quantum for a new timeslice."""
        self.quantum_remaining = self._initial_quantum()
        self.first_timeslice = True

    def __repr__(self) -> str:
        bucket_name = {
            TH_BUCKET_FIXPRI: "FP",
            TH_BUCKET_SHARE_FG: "FG",
            TH_BUCKET_SHARE_IN: "IN",
            TH_BUCKET_SHARE_DF: "DF",
            TH_BUCKET_SHARE_UT: "UT",
            TH_BUCKET_SHARE_BG: "BG",
        }.get(self.th_sched_bucket, "??")
        return f"Thread({self.name}, pri={self.sched_pri}, bucket={bucket_name}, {self.state.name})"


def _convert_pri_to_bucket(pri: int) -> int:
    """Map a priority to a timeshare scheduling bucket.

    Ports sched_convert_pri_to_bucket() from sched_clutch.c:353-370.
    """
    if pri > BASEPRI_USER_INITIATED:
        return TH_BUCKET_SHARE_FG
    elif pri > BASEPRI_DEFAULT:
        return TH_BUCKET_SHARE_IN
    elif pri > BASEPRI_UTILITY:
        return TH_BUCKET_SHARE_DF
    elif pri > MAXPRI_THROTTLE:
        return TH_BUCKET_SHARE_UT
    else:
        return TH_BUCKET_SHARE_BG


def thread_bucket_map(sched_mode: int, base_pri: int) -> int:
    """Map a thread to its scheduling bucket.

    Ports sched_clutch_thread_bucket_map() from sched_clutch.c:378-399.
    """
    if sched_mode == TH_MODE_REALTIME:
        return TH_BUCKET_FIXPRI

    if sched_mode == TH_MODE_FIXED:
        if base_pri >= BASEPRI_FOREGROUND:
            return TH_BUCKET_FIXPRI
        else:
            return _convert_pri_to_bucket(base_pri)

    # Timeshare: always use priority-based bucket (never FIXPRI)
    return _convert_pri_to_bucket(base_pri)
