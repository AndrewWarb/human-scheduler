"""
Timeshare scheduling logic: priority decay, load calculation, CPU aging.

Ports the Mach timeshare decay algorithm as used within the Clutch scheduler:
  - sched_clutch.c:1980-2083 (pri_shift_update, timeshare_update)
  - sched_average.c:250-300 (compute_sched_pri equivalent)
  - sched_clutch.c:1688-1978 (interactivity scoring, CPU data aging)
"""

from __future__ import annotations

from .constants import (
    MINPRI,
    SCHED_FIXED_SHIFT,
    SCHED_LOAD_SHIFTS,
    SCHED_PRI_SHIFT_MAX,
    SCHED_DECAY_TICKS,
    SCHED_DECAY_SHIFTS,
    NRQS,
    SCHED_TICK_INTERVAL_US,
    SCHED_CLUTCH_BUCKET_GROUP_INTERACTIVE_PRI_DEFAULT,
    is_above_timeshare,
)
from .thread import Thread
from .clutch import SchedClutchBucketGroup


def compute_sched_pri(thread: Thread, cbg: SchedClutchBucketGroup) -> int:
    """Compute the effective scheduling priority for a timeshare thread.

    This implements the Mach timeshare decay: priority drops as the thread
    accumulates CPU usage, with the rate controlled by pri_shift.

    pri_shift is higher when load is low (slower decay) and lower when
    load is high (faster decay), ensuring fair CPU sharing under contention.

    sched_pri = base_pri - (sched_usage >> pri_shift)
    """
    if is_above_timeshare(cbg.scbg_bucket):
        # Fixed-priority threads don't decay
        return thread.base_pri

    # XNU hard-bound threads bypass Clutch pri_shift and effectively see INT8_MAX.
    if thread.bound_processor is not None:
        return thread.base_pri

    pri_shift = thread.pri_shift
    if pri_shift >= 127:
        # No decay
        return thread.base_pri

    decay = thread.sched_usage >> pri_shift
    sched_pri = thread.base_pri - decay
    return max(MINPRI, min(sched_pri, thread.max_priority))


def update_thread_cpu_usage(
    thread: Thread, delta_us: int, cbg: SchedClutchBucketGroup
) -> None:
    """Update a thread's CPU usage counter after running.

    XNU tracks timeshare decay from sched_usage, and only charges that counter
    when the previous window was contended (pri_shift < INT8_MAX).
    """
    thread.cpu_usage += delta_us
    if thread.pri_shift < 127:
        thread.sched_usage += delta_us
    thread.cpu_delta += delta_us

    # Hard-bound threads are not Clutch-eligible in XNU and must not
    # perturb clutch bucket-group CPU/interactivity accounting.
    if thread.bound_processor is None:
        cbg.cpu_usage_update(delta_us)


def age_thread_cpu_usage(thread: Thread, decay_factor: int = 1) -> None:
    """Age (decay) a thread's accumulated CPU usage.

    Called periodically (each sched_tick) to allow threads to regain priority
    after being penalized for CPU usage.

    Mirrors XNU update_priority() behavior:
    - use sched_decay_shifts[ticks] approximation for usage aging
    - zero usage when ticks >= SCHED_DECAY_TICKS
    """
    ticks = max(0, decay_factor)
    if ticks >= SCHED_DECAY_TICKS:
        thread.cpu_usage = 0
        thread.sched_usage = 0
        thread.cpu_delta = 0
        return

    shift1, shift2 = SCHED_DECAY_SHIFTS[ticks]
    if shift2 > 0:
        thread.cpu_usage = (thread.cpu_usage >> shift1) + (thread.cpu_usage >> shift2)
        thread.sched_usage = (thread.sched_usage >> shift1) + (
            thread.sched_usage >> shift2
        )
    else:
        thread.cpu_usage = (thread.cpu_usage >> shift1) - (thread.cpu_usage >> (-shift2))
        thread.sched_usage = (thread.sched_usage >> shift1) - (
            thread.sched_usage >> (-shift2)
        )
    thread.cpu_delta = 0


def pri_shift_for_load(run_count: int, processor_count: int) -> int:
    """Calculate priority shift based on load.

    Higher load -> lower pri_shift -> faster priority decay.
    This ensures CPU-bound threads at the same QoS level timeshare fairly.

    Ports the logic from sched_clutch_bucket_group_pri_shift_update().
    """
    if processor_count == 0:
        return 127  # INT8_MAX: no decay

    # Subtract 1 so NCPU-wide workloads don't experience decay
    effective_run_count = max(0, run_count - 1)
    load = effective_run_count // processor_count
    load = min(load, NRQS - 1)

    pri_shift = SCHED_FIXED_SHIFT - SCHED_LOAD_SHIFTS[load]
    if pri_shift > SCHED_PRI_SHIFT_MAX:
        return 127  # INT8_MAX

    return pri_shift
