"""
XNU Clutch Scheduler constants, faithfully ported from:
  - osfmk/kern/sched.h
  - osfmk/kern/sched_clutch.c
  - osfmk/kern/sched_prim.c
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Priority levels (sched.h:79-177)
# ---------------------------------------------------------------------------
NRQS_MAX: int = 128
MAXPRI: int = NRQS_MAX - 1  # 127
MINPRI: int = 0
IDLEPRI: int = MINPRI
NOPRI: int = -1

# Realtime deadline sentinels (sched.h:296-297)
RT_DEADLINE_NONE: int = 0xFFFFFFFFFFFFFFFF
RT_DEADLINE_QUANTUM_EXPIRED: int = 0xFFFFFFFFFFFFFFFE

BASEPRI_REALTIME: int = MAXPRI - (NRQS_MAX // 4) + 1  # 96
BASEPRI_RTQUEUES: int = BASEPRI_REALTIME + 1  # 97

MAXPRI_KERNEL: int = BASEPRI_REALTIME - 1  # 95
BASEPRI_PREEMPT: int = MAXPRI_KERNEL - 3  # 92
BASEPRI_PREEMPT_HIGH: int = BASEPRI_PREEMPT + 1  # 93
BASEPRI_VM: int = BASEPRI_PREEMPT - 1  # 91

BASEPRI_KERNEL: int = MAXPRI_KERNEL - (NRQS_MAX // 8) + 2  # 81
MINPRI_KERNEL: int = MAXPRI_KERNEL - (NRQS_MAX // 8) + 1  # 80

MAXPRI_RESERVED: int = MINPRI_KERNEL - 1  # 79
MINPRI_RESERVED: int = MAXPRI_RESERVED - (NRQS_MAX // 8) + 1  # 64

MAXPRI_USER: int = MINPRI_RESERVED - 1  # 63
BASEPRI_DEFAULT: int = MAXPRI_USER - (NRQS_MAX // 4)  # 31
BASEPRI_CONTROL: int = BASEPRI_DEFAULT + 17  # 48
BASEPRI_FOREGROUND: int = BASEPRI_DEFAULT + 16  # 47
BASEPRI_BACKGROUND: int = BASEPRI_DEFAULT + 15  # 46
BASEPRI_USER_INITIATED: int = BASEPRI_DEFAULT + 6  # 37
MAXPRI_SUPPRESSED: int = BASEPRI_DEFAULT - 3  # 28
BASEPRI_UTILITY: int = BASEPRI_DEFAULT - 11  # 20
MAXPRI_THROTTLE: int = MINPRI + 4  # 4
MINPRI_USER: int = MINPRI  # 0

NRQS: int = BASEPRI_REALTIME  # 96 - non-realtime levels
NRTQS: int = MAXPRI - BASEPRI_REALTIME  # 31 - realtime levels

# Priority promotion ceiling
MAXPRI_PROMOTE: int = MAXPRI_KERNEL  # 95

# ---------------------------------------------------------------------------
# Scheduler bucket enum (sched.h:222-234, CONFIG_SCHED_CLUTCH variant)
# ---------------------------------------------------------------------------
TH_BUCKET_FIXPRI: int = 0  # Fixed-priority (Above UI)
TH_BUCKET_SHARE_FG: int = 1  # Foreground
TH_BUCKET_SHARE_IN: int = 2  # User-Initiated (Clutch-only)
TH_BUCKET_SHARE_DF: int = 3  # Default
TH_BUCKET_SHARE_UT: int = 4  # Utility
TH_BUCKET_SHARE_BG: int = 5  # Background
TH_BUCKET_RUN: int = 6  # All runnable (sentinel)
TH_BUCKET_SCHED_MAX: int = TH_BUCKET_RUN  # 6 - max schedulable buckets
TH_BUCKET_MAX: int = 7

BUCKET_NAMES: dict[int, str] = {
    TH_BUCKET_FIXPRI: "FIXPRI",
    TH_BUCKET_SHARE_FG: "FG",
    TH_BUCKET_SHARE_IN: "IN",
    TH_BUCKET_SHARE_DF: "DF",
    TH_BUCKET_SHARE_UT: "UT",
    TH_BUCKET_SHARE_BG: "BG",
}

# ---------------------------------------------------------------------------
# Thread sched_mode (sched.h:184-189)
# ---------------------------------------------------------------------------
TH_MODE_REALTIME: int = 1
TH_MODE_FIXED: int = 2
TH_MODE_TIMESHARE: int = 3

# ---------------------------------------------------------------------------
# SCHED_CLUTCH_INVALID sentinels (sched_clutch.c)
# ---------------------------------------------------------------------------
SCHED_CLUTCH_INVALID_TIME_32: int = 0xFFFFFFFF
SCHED_CLUTCH_INVALID_TIME_64: int = 0xFFFFFFFFFFFFFFFF

# ---------------------------------------------------------------------------
# Root bucket WCEL (worst-case execution latency) in microseconds
# (sched_clutch.c:199-206)
# ---------------------------------------------------------------------------
ROOT_BUCKET_WCEL_US: list[int] = [
    SCHED_CLUTCH_INVALID_TIME_32,  # FIXPRI (not used for EDF)
    0,       # FG
    37500,   # IN (37.5ms)
    75000,   # DF (75ms)
    150000,  # UT (150ms)
    250000,  # BG (250ms)
]

# ---------------------------------------------------------------------------
# Root bucket warp budgets in microseconds (sched_clutch.c:223-230)
# ---------------------------------------------------------------------------
SCHED_CLUTCH_ROOT_BUCKET_WARP_UNUSED: int = SCHED_CLUTCH_INVALID_TIME_64

ROOT_BUCKET_WARP_US: list[int] = [
    SCHED_CLUTCH_INVALID_TIME_32,  # FIXPRI
    8000,   # FG (8ms)
    4000,   # IN (4ms)
    2000,   # DF (2ms)
    1000,   # UT (1ms)
    0,      # BG (0ms)
]

# ---------------------------------------------------------------------------
# Thread quantum per bucket in microseconds (sched_clutch.c:251-258, non-macOS)
# ---------------------------------------------------------------------------
THREAD_QUANTUM_US: list[int] = [
    10000,  # FIXPRI (10ms)
    10000,  # FG (10ms)
    8000,   # IN (8ms)
    6000,   # DF (6ms)
    4000,   # UT (4ms)
    2000,   # BG (2ms)
]

# ---------------------------------------------------------------------------
# Interactivity scoring (sched_clutch.c:1319-1334)
# ---------------------------------------------------------------------------
SCHED_CLUTCH_BUCKET_GROUP_INTERACTIVE_PRI_DEFAULT: int = 8
SCHED_CLUTCH_BUCKET_GROUP_ADJUST_THRESHOLD_US: int = 500_000  # 500ms
SCHED_CLUTCH_BUCKET_GROUP_ADJUST_RATIO: int = 10

# Initial interactivity score = interactive_pri * 2 (see line 1413)
SCHED_CLUTCH_BUCKET_GROUP_INITIAL_INTERACTIVITY: int = (
    SCHED_CLUTCH_BUCKET_GROUP_INTERACTIVE_PRI_DEFAULT * 2
)

# Sentinel for "no blocked timestamp"
SCHED_CLUTCH_BUCKET_GROUP_BLOCKED_TS_INVALID: int = SCHED_CLUTCH_INVALID_TIME_64
SCHED_CLUTCH_BUCKET_GROUP_PENDING_INVALID: int = SCHED_CLUTCH_INVALID_TIME_64

# ---------------------------------------------------------------------------
# Timeshare decay (sched.h:385-389, sched_prim.c:400-718)
# ---------------------------------------------------------------------------
SCHED_PRI_SHIFT_MAX: int = (8 * 4) - 1  # 31 (sizeof(uint32_t)*8 - 1)
MAX_LOAD: int = NRQS - 1  # 95

# sched_fixed_shift: computed at boot from abstime conversion, but for
# simulation with 1us = 1 unit, we derive it from the algorithm:
#   abstime = (abstime * 5) / 3
#   shift until abstime <= BASEPRI_DEFAULT
# For our simulation: abstime starts at quantum (~10000us), we pick a
# reasonable value matching typical macOS. On real hardware this is ~31.
SCHED_FIXED_SHIFT: int = 31

# update_priority() applies a precomputed shift approximation table for
# (5/8)^ticks aging and zeroes usage at/after this bound.
SCHED_DECAY_TICKS: int = 32

# sched_decay_shifts[] from priority.c (index 0 is identity, index n applies n ticks).
SCHED_DECAY_SHIFTS: list[tuple[int, int]] = [
    (1, 1),
    (1, 3),
    (1, -3),
    (2, -7),
    (3, 5),
    (3, -5),
    (4, -8),
    (5, 7),
    (5, -7),
    (6, -10),
    (7, 10),
    (7, -9),
    (8, -11),
    (9, 12),
    (9, -11),
    (10, -13),
    (11, 14),
    (11, -13),
    (12, -15),
    (13, 17),
    (13, -15),
    (14, -17),
    (15, 19),
    (16, 18),
    (16, -19),
    (17, 22),
    (18, 20),
    (18, -20),
    (19, 26),
    (20, 22),
    (20, -22),
    (21, -27),
]

# ---------------------------------------------------------------------------
# sched_load_shifts[] table (sched_prim.c:676-718)
#
# Generated by load_shift_init() with sched_decay_penalty=1:
#   shifts[0] = INT8_MIN (-128)
#   shifts[1] = 0
#   For i in 2..NRQS-1: k such that 2^(k+penalty) > i >= 2^(k+penalty-1)
#   This means: 2->3 get k=1, 4->7 get k=2, 8->15 get k=3, etc.
# ---------------------------------------------------------------------------
def _compute_load_shifts(nrqs: int = NRQS, decay_penalty: int = 1) -> list[int]:
    """Reproduce XNU's load_shift_init() from sched_prim.c:676-718."""
    shifts = [0] * nrqs
    shifts[0] = -128  # INT8_MIN
    shifts[1] = 0
    idx = 2
    j = 1 << decay_penalty  # j = 2
    k = 1
    while idx < nrqs:
        j <<= 1  # j = 4, 8, 16, ...
        while idx < j and idx < nrqs:
            shifts[idx] = k
            idx += 1
        k += 1
    return shifts


SCHED_LOAD_SHIFTS: list[int] = _compute_load_shifts()

# ---------------------------------------------------------------------------
# Scheduler tick interval
# ---------------------------------------------------------------------------
SCHED_TICK_INTERVAL_US: int = 125_000  # 125ms per sched_tick

# ---------------------------------------------------------------------------
# Pending delta for clutch bucket group (sched_clutch.c)
# Interval at which pending data is sampled for interactivity aging
# ---------------------------------------------------------------------------
SCHED_CLUTCH_BUCKET_GROUP_PENDING_DELTA_US: list[int] = [
    SCHED_CLUTCH_INVALID_TIME_32,  # FIXPRI
    10000,   # FG (10ms)
    37500,   # IN (37.5ms)
    75000,   # DF (75ms)
    150000,  # UT (150ms)
    250000,  # BG (250ms)
]

# ---------------------------------------------------------------------------
# Enqueue options (matching XNU's sched_prim.h sched_options_t values)
# ---------------------------------------------------------------------------
SCHED_TAILQ: int = 0x1  # enqueue at tail
SCHED_HEADQ: int = 0x2  # enqueue at head
SCHED_PREEMPT: int = 0x4

# Clutch bucket options
SCHED_CLUTCH_BUCKET_OPTIONS_NONE: int = 0x0
SCHED_CLUTCH_BUCKET_OPTIONS_SAMEPRI_RR: int = 0x1
SCHED_CLUTCH_BUCKET_OPTIONS_HEADQ: int = 0x2
SCHED_CLUTCH_BUCKET_OPTIONS_TAILQ: int = 0x4


def is_above_timeshare(bucket: int) -> bool:
    """Check if a bucket is the fixed-priority Above UI bucket.

    Ports sched_clutch_bucket_is_above_timeshare().
    """
    return bucket == TH_BUCKET_FIXPRI
