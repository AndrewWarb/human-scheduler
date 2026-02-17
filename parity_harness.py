#!/usr/bin/env python3
"""
Deterministic parity checks for the XNU scheduler simulation.

This harness focuses on decision points that should match XNU semantics:
- stable runqueue ordering (preempted/non-preempted tie behavior)
- RT runqueue dequeue policy (priority-first + conditional EDF override)
- RT current-thread keep-running checks during selection/preemption
"""

from __future__ import annotations

from dataclasses import dataclass

from xnu_sched.constants import (
    TH_MODE_REALTIME,
    TH_MODE_FIXED,
    BASEPRI_RTQUEUES,
    BASEPRI_PREEMPT,
    RT_DEADLINE_NONE,
    RT_DEADLINE_QUANTUM_EXPIRED,
    SCHED_HEADQ,
    SCHED_TAILQ,
    SCHED_PREEMPT,
)
from xnu_sched.clutch import SchedClutch
from xnu_sched.priority_queue import StablePriorityQueue
from xnu_sched.processor import ProcessorSet
from xnu_sched.scheduler import Scheduler
from xnu_sched.rt_queue import RTQueue
from xnu_sched.thread import Thread, ThreadGroup, ThreadState
from xnu_sched.timeshare import (
    compute_sched_pri,
    update_thread_cpu_usage,
    age_thread_cpu_usage,
)
from simulator.engine import SimulationEngine
from simulator.events import Event, EventType
from simulator.workload import BehaviorProfile


@dataclass
class _PQItem:
    name: str
    pri: int


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)


def _new_tg(name: str) -> ThreadGroup:
    tg = ThreadGroup(name)
    SchedClutch(tg, num_clusters=1)
    return tg


def _new_rt_thread(
    tg: ThreadGroup,
    name: str,
    pri: int,
    deadline: int,
    computation: int = 100,
    constraint: int = 1000,
) -> Thread:
    t = Thread(
        thread_group=tg,
        sched_mode=TH_MODE_REALTIME,
        base_pri=pri,
        name=name,
        rt_period=0,
        rt_computation=computation,
        rt_constraint=constraint,
    )
    t.rt_deadline = deadline
    return t


def _new_sched(num_cpus: int = 1) -> tuple[Scheduler, object]:
    pset = ProcessorSet(num_cpus=num_cpus)
    sched = Scheduler(pset, trace=False)
    return sched, pset.processors[0]


def _dispatch_current(sched: Scheduler, proc, thread: Thread, ts: int = 0) -> None:
    sched.thread_dispatch(proc, None, thread, ts)


def test_stable_runqueue_ordering() -> None:
    q: StablePriorityQueue[_PQItem] = StablePriorityQueue(lambda it: it.pri)

    # Non-preempted ties: older stamp first.
    a = _PQItem("a", 50)
    b = _PQItem("b", 50)
    q.insert(a, preempted=False, stamp=10)
    q.insert(b, preempted=False, stamp=20)
    _assert(q.pop_max() is a, "non-preempted tie should prefer older stamp")
    _assert(q.pop_max() is b, "non-preempted second pop mismatch")

    # Preempted ties: younger stamp first.
    q.insert(a, preempted=True, stamp=10)
    q.insert(b, preempted=True, stamp=20)
    _assert(q.pop_max() is b, "preempted tie should prefer younger stamp")
    _assert(q.pop_max() is a, "preempted second pop mismatch")

    # Preempted entries with identical stamp should still prefer newest insert
    # (head insertion semantics at equal timestamp).
    q.insert(a, preempted=True, stamp=30)
    q.insert(b, preempted=True, stamp=30)
    _assert(
        q.pop_max() is b,
        "preempted equal-stamp tie should prefer most recent insertion",
    )
    _assert(q.pop_max() is a, "preempted equal-stamp second pop mismatch")

    # Preempted should outrank non-preempted at same priority.
    q.insert(a, preempted=False, stamp=30)
    q.insert(b, preempted=True, stamp=5)
    _assert(q.pop_max() is b, "preempted entry should outrank non-preempted tie")
    _assert(q.pop_max() is a, "same-pri remaining item mismatch")

    # Higher priority always wins regardless of preempted modifier.
    hi = _PQItem("hi", 51)
    lo = _PQItem("lo", 50)
    q.insert(lo, preempted=True, stamp=999)
    q.insert(hi, preempted=False, stamp=1)
    _assert(q.pop_max() is hi, "higher priority must outrank lower priority")
    _assert(q.pop_max() is lo, "lower priority should remain after higher")


def test_rt_runqueue_policy() -> None:
    tg = _new_tg("rt-policy")

    # Same RT priority should dequeue earliest deadline first.
    rq = RTQueue()
    t1 = _new_rt_thread(tg, "same-pri-late", BASEPRI_RTQUEUES + 2, 3000)
    t2 = _new_rt_thread(tg, "same-pri-early", BASEPRI_RTQUEUES + 2, 1000)
    rq.enqueue(t1)
    rq.enqueue(t2)
    _assert(rq.dequeue() is t2, "same-priority RT dequeue must be deadline-ordered")

    # Lower-priority earliest-deadline thread can win when safe (EDF override).
    rq = RTQueue()
    hi_safe = _new_rt_thread(
        tg, "hi-safe", BASEPRI_RTQUEUES + 4, 5000, computation=300, constraint=3000
    )
    lo_earlier = _new_rt_thread(
        tg, "lo-earlier", BASEPRI_RTQUEUES + 3, 1000, computation=200, constraint=2000
    )
    rq.enqueue(hi_safe)
    rq.enqueue(lo_earlier)
    _assert(
        rq.dequeue() is lo_earlier,
        "RT EDF override should choose earlier deadline when constraint is safe",
    )

    # Override must be rejected when it would violate higher-priority constraint.
    rq = RTQueue()
    hi_unsafe = _new_rt_thread(
        tg, "hi-unsafe", BASEPRI_RTQUEUES + 4, 5000, computation=1200, constraint=1300
    )
    lo_earlier_unsafe = _new_rt_thread(
        tg,
        "lo-earlier-unsafe",
        BASEPRI_RTQUEUES + 3,
        1000,
        computation=300,
        constraint=2000,
    )
    rq.enqueue(hi_unsafe)
    rq.enqueue(lo_earlier_unsafe)
    _assert(
        rq.dequeue() is hi_unsafe,
        "RT should keep higher priority when EDF override is not constraint-safe",
    )

    # Equal earliest deadlines across priorities should prefer higher priority.
    rq = RTQueue()
    hi_equal = _new_rt_thread(
        tg, "hi-equal", BASEPRI_RTQUEUES + 4, 4000, computation=100, constraint=1200
    )
    lo_equal = _new_rt_thread(
        tg, "lo-equal", BASEPRI_RTQUEUES + 3, 4000, computation=100, constraint=1200
    )
    rq.enqueue(lo_equal)
    rq.enqueue(hi_equal)
    _assert(
        rq.dequeue() is hi_equal,
        "RT equal-deadline tie across priorities must prefer higher-priority band",
    )


def test_rt_prev_thread_keep_running_and_preempt() -> None:
    tg = _new_tg("rt-prev")

    # Later-deadline peer should not force switch on first timeslice.
    sched, proc = _new_sched(num_cpus=1)
    prev = _new_rt_thread(tg, "prev", BASEPRI_RTQUEUES + 2, 5000, computation=200)
    _dispatch_current(sched, proc, prev, ts=0)
    later = _new_rt_thread(tg, "later", BASEPRI_RTQUEUES + 2, 9000, computation=100)
    _assert(
        sched.thread_setrun(later, 10) is None,
        "later deadline RT peer should not request immediate preemption",
    )
    selected, chose_prev = sched.thread_select(proc, 20, prev_thread=prev)
    _assert(selected is prev and chose_prev, "prev RT should keep running on first timeslice")

    # Earlier-deadline peer at same priority should preempt.
    sched, proc = _new_sched(num_cpus=1)
    prev = _new_rt_thread(tg, "prev2", BASEPRI_RTQUEUES + 2, 8000, computation=200)
    _dispatch_current(sched, proc, prev, ts=0)
    earlier = _new_rt_thread(tg, "earlier", BASEPRI_RTQUEUES + 2, 1000, computation=100)
    _assert(
        sched.thread_setrun(earlier, 10) is proc,
        "earlier deadline RT peer should request preemption",
    )
    selected, chose_prev = sched.thread_select(proc, 20, prev_thread=prev)
    _assert(selected is earlier and not chose_prev, "earlier deadline RT should be selected")


def test_rt_higher_priority_constraint_gate() -> None:
    tg = _new_tg("rt-higher-pri")

    # Higher-priority RT can be deferred if constraint-safe.
    sched, proc = _new_sched(num_cpus=1)
    prev = _new_rt_thread(tg, "prev-safe", BASEPRI_RTQUEUES + 1, 8000, computation=100)
    _dispatch_current(sched, proc, prev, ts=0)
    hi_safe = _new_rt_thread(
        tg, "hi-safe", BASEPRI_RTQUEUES + 3, 9000, computation=100, constraint=1000
    )
    sched.thread_setrun(hi_safe, 10)
    selected, chose_prev = sched.thread_select(proc, 20, prev_thread=prev)
    _assert(
        selected is prev and chose_prev,
        "higher-priority RT should be deferrable when constraint check is safe",
    )

    # Higher-priority RT must preempt when not constraint-safe.
    sched, proc = _new_sched(num_cpus=1)
    prev = _new_rt_thread(
        tg, "prev-unsafe", BASEPRI_RTQUEUES + 1, 8000, computation=200
    )
    _dispatch_current(sched, proc, prev, ts=0)
    hi_unsafe = _new_rt_thread(
        tg, "hi-unsafe", BASEPRI_RTQUEUES + 3, 9000, computation=120, constraint=350
    )
    sched.thread_setrun(hi_unsafe, 10)
    selected, chose_prev = sched.thread_select(proc, 20, prev_thread=prev)
    _assert(
        selected is hi_unsafe and not chose_prev,
        "higher-priority RT should preempt when constraint check fails",
    )


def test_rt_non_first_timeslice_forces_pick_from_runq() -> None:
    tg = _new_tg("rt-non-first")
    sched, proc = _new_sched(num_cpus=1)

    prev = _new_rt_thread(
        tg, "prev-rt", BASEPRI_RTQUEUES + 2, 9000, computation=100, constraint=1000
    )
    _dispatch_current(sched, proc, prev, ts=0)
    proc.first_timeslice = False

    queued = _new_rt_thread(
        tg, "queued-rt", BASEPRI_RTQUEUES + 2, 12000, computation=100, constraint=1000
    )
    sched.thread_setrun(queued, 10)
    selected, chose_prev = sched.thread_select(proc, 20, prev_thread=prev)
    _assert(
        selected is queued and not chose_prev,
        "non-first-timeslice RT should pick from RT runq instead of keeping prev",
    )


def test_rt_setrun_non_first_timeslice_does_not_preempt_without_better_rt() -> None:
    tg = _new_tg("rt-setrun-no-forced-preempt")
    sched, proc = _new_sched(num_cpus=1)

    active = _new_rt_thread(
        tg, "active-rt", BASEPRI_RTQUEUES + 3, deadline=1000, computation=100, constraint=2000
    )
    _dispatch_current(sched, proc, active, ts=0)
    proc.first_timeslice = False

    lower = _new_rt_thread(
        tg, "lower-rt", BASEPRI_RTQUEUES + 2, deadline=500, computation=100, constraint=2000
    )
    preempt_proc = sched.thread_setrun(lower, 10)
    _assert(
        preempt_proc is None,
        "RT enqueue should not force preemption for lower-priority candidate on non-first-timeslice",
    )

    equal_later = _new_rt_thread(
        tg, "equal-later-rt", BASEPRI_RTQUEUES + 3, deadline=1800, computation=100, constraint=2000
    )
    preempt_proc = sched.thread_setrun(equal_later, 20)
    _assert(
        preempt_proc is None,
        "RT enqueue should not force preemption for equal-priority later-deadline candidate",
    )


def test_bound_prev_not_considered_in_clutch_hierarchy() -> None:
    tg = _new_tg("bound-prev")
    sched, proc = _new_sched(num_cpus=1)

    prev = Thread(thread_group=tg, base_pri=47, name="prev-bound")
    contender = Thread(thread_group=tg, base_pri=48, name="contender")

    _dispatch_current(sched, proc, prev, ts=0)
    prev.bound_processor = proc

    sched.thread_setrun(contender, 10)
    selected, chose_prev = sched.thread_select(proc, 20, prev_thread=prev)
    _assert(
        selected is contender and not chose_prev,
        "processor-bound prev thread must not participate in clutch hierarchy selection",
    )


def test_bound_queue_tie_breaks_over_clutch() -> None:
    tg = _new_tg("bound-vs-clutch")
    sched, proc = _new_sched(num_cpus=1)

    # Default clutch boost is +16 for this bucket at startup, so base 47 maps
    # to root clutch priority 63. Match that with a bound raw priority of 63.
    bound = Thread(thread_group=tg, base_pri=63, name="bound")
    bound.bound_processor = proc
    clutch = Thread(thread_group=tg, base_pri=47, name="clutch")

    sched.thread_setrun(bound, 10)
    sched.thread_setrun(clutch, 10)
    selected, chose_prev = sched.thread_select(proc, 20, prev_thread=None)
    _assert(
        selected is bound and not chose_prev,
        "bound runqueue should win ties against clutch hierarchy",
    )


def test_root_priority_uses_raw_thread_pri_not_interactivity() -> None:
    tg = _new_tg("root-pri-raw")
    sched, proc = _new_sched(num_cpus=1)

    # Same raw sched_pri on both sides, but clutch bucket priority is boosted by
    # interactivity. XNU root_pri_update compares using raw thread priority,
    # so bound side should win the tie.
    bound = Thread(thread_group=tg, base_pri=47, name="bound-raw47")
    bound.bound_processor = proc
    sched.thread_setrun(bound, 10)

    clutch = Thread(thread_group=tg, base_pri=47, name="clutch-raw47")
    sched.thread_setrun(clutch, 10)

    selected, chose_prev = sched.thread_select(proc, 20, prev_thread=None)
    _assert(
        selected is bound and not chose_prev,
        "root priority comparison should use raw thread pri, not interactivity-boosted pri",
    )


def test_bound_preemption_targets_bound_cpu() -> None:
    tg = _new_tg("bound-preempt")
    sched = Scheduler(ProcessorSet(num_cpus=2), trace=False)
    p0 = sched.pset.processors[0]
    p1 = sched.pset.processors[1]

    r0 = Thread(thread_group=tg, base_pri=10, name="r0")
    r1 = Thread(thread_group=tg, base_pri=40, name="r1")
    sched.thread_dispatch(p0, None, r0, 0)
    sched.thread_dispatch(p1, None, r1, 0)

    low_bound = Thread(thread_group=tg, base_pri=30, name="low-bound")
    low_bound.bound_processor = p1
    _assert(
        sched.thread_setrun(low_bound, 10, options=(SCHED_PREEMPT | SCHED_TAILQ)) is None,
        "bound thread below target priority should not preempt any CPU",
    )

    hi_bound = Thread(thread_group=tg, base_pri=50, name="hi-bound")
    hi_bound.bound_processor = p1
    _assert(
        sched.thread_setrun(hi_bound, 20, options=(SCHED_PREEMPT | SCHED_TAILQ)) is p1,
        "bound thread should preempt only its target CPU",
    )


def test_non_preempt_enqueue_does_not_force_nonurgent_cross_cpu_preempt() -> None:
    tg = _new_tg("nonpreempt-gate")
    sched = Scheduler(ProcessorSet(num_cpus=2), trace=False)
    p0 = sched.pset.processors[0]
    p1 = sched.pset.processors[1]

    r0 = Thread(thread_group=tg, base_pri=40, name="r0")
    r1 = Thread(thread_group=tg, base_pri=20, name="r1")
    sched.thread_dispatch(p0, None, r0, 0)
    sched.thread_dispatch(p1, None, r1, 0)

    queued = Thread(thread_group=tg, base_pri=30, name="queued")
    _assert(
        sched.thread_setrun(queued, 10, options=SCHED_HEADQ) is None,
        "non-urgent enqueue without SCHED_PREEMPT should not force cross-CPU preemption",
    )


def test_non_preempt_enqueue_still_preempts_for_urgent_priority() -> None:
    tg = _new_tg("nonpreempt-urgent")
    sched = Scheduler(ProcessorSet(num_cpus=2), trace=False)
    p0 = sched.pset.processors[0]
    p1 = sched.pset.processors[1]

    r0 = Thread(thread_group=tg, base_pri=40, name="r0")
    r1 = Thread(thread_group=tg, base_pri=20, name="r1")
    sched.thread_dispatch(p0, None, r0, 0)
    sched.thread_dispatch(p1, None, r1, 0)

    urgent = Thread(
        thread_group=tg,
        sched_mode=TH_MODE_FIXED,
        base_pri=BASEPRI_PREEMPT + 1,
        name="urgent",
    )
    _assert(
        sched.thread_setrun(urgent, 10, options=SCHED_HEADQ) is p1,
        "urgent priority should preempt even without explicit SCHED_PREEMPT option",
    )


def test_equal_priority_preempt_requires_preempt_option_and_non_first_timeslice() -> None:
    tg = _new_tg("equal-pri-preempt")
    sched = Scheduler(ProcessorSet(num_cpus=1), trace=False)
    proc = sched.pset.processors[0]

    active = Thread(thread_group=tg, base_pri=40, name="active")
    sched.thread_dispatch(proc, None, active, 0)
    proc.first_timeslice = False

    peer = Thread(thread_group=tg, base_pri=40, name="peer")
    _assert(
        sched.thread_setrun(peer, 10, options=SCHED_TAILQ) is None,
        "equal-priority enqueue without SCHED_PREEMPT should not force preemption",
    )

    peer2 = Thread(thread_group=tg, base_pri=40, name="peer2")
    _assert(
        sched.thread_setrun(peer2, 11, options=(SCHED_PREEMPT | SCHED_TAILQ)) is proc,
        "equal-priority enqueue with SCHED_PREEMPT should preempt once current is past first_timeslice",
    )


def test_equal_urgent_priority_without_preempt_does_not_preempt() -> None:
    tg = _new_tg("equal-urgent-no-preempt")
    sched = Scheduler(ProcessorSet(num_cpus=1), trace=False)
    proc = sched.pset.processors[0]

    pri = BASEPRI_PREEMPT + 2
    active = Thread(thread_group=tg, sched_mode=TH_MODE_FIXED, base_pri=pri, name="active-urgent")
    sched.thread_dispatch(proc, None, active, 0)
    proc.first_timeslice = False

    peer = Thread(thread_group=tg, sched_mode=TH_MODE_FIXED, base_pri=pri, name="peer-urgent")
    _assert(
        sched.thread_setrun(peer, 10, options=SCHED_TAILQ) is None,
        "equal urgent-priority enqueue without SCHED_PREEMPT should not force preemption",
    )


def test_equal_priority_with_preempt_still_signals_on_first_timeslice() -> None:
    tg = _new_tg("equal-pri-first-signal")
    sched = Scheduler(ProcessorSet(num_cpus=1), trace=False)
    proc = sched.pset.processors[0]

    active = Thread(thread_group=tg, base_pri=40, name="active-first")
    sched.thread_dispatch(proc, None, active, 0)
    _assert(proc.first_timeslice, "dispatch should begin on first timeslice")

    peer = Thread(thread_group=tg, base_pri=40, name="peer-first")
    _assert(
        sched.thread_setrun(peer, 10, options=(SCHED_PREEMPT | SCHED_TAILQ)) is proc,
        "equal-priority enqueue with SCHED_PREEMPT should signal preemption even on first timeslice",
    )

    selected, chose_prev = sched.thread_select(proc, 20, prev_thread=active)
    _assert(
        selected is active and chose_prev,
        "first-timeslice tie should still keep current thread running",
    )


def test_rt_higher_pri_safe_does_not_preempt_by_deadline_fallthrough() -> None:
    tg = _new_tg("rt-safe-fallthrough")
    sched = Scheduler(ProcessorSet(num_cpus=1), trace=False)
    proc = sched.pset.processors[0]

    active = _new_rt_thread(
        tg, "active", BASEPRI_RTQUEUES + 1, 12000, computation=100, constraint=1000
    )
    sched.thread_dispatch(proc, None, active, 0)

    queued = _new_rt_thread(
        tg, "queued", BASEPRI_RTQUEUES + 3, 1000, computation=100, constraint=1000
    )
    # realtime_setrun() raises preemption for higher-priority RT arrivals.
    # thread_select() then keeps current RT on first_timeslice when constraint-safe.
    _assert(
        sched.thread_setrun(queued, 10) is proc,
        "higher-priority RT enqueue should request preemption",
    )
    selected, chose_prev = sched.thread_select(proc, 20, prev_thread=active)
    _assert(
        selected is active and chose_prev,
        "constraint-safe higher-priority RT should still allow current RT to continue on first timeslice",
    )


def test_sched_tick_refreshes_thread_runq_after_priority_changes() -> None:
    tg = _new_tg("tick-refresh")
    sched, proc = _new_sched(num_cpus=1)

    a = Thread(thread_group=tg, base_pri=31, name="a")
    b = Thread(thread_group=tg, base_pri=31, name="b")
    sched.thread_setrun(a, 0)
    sched.thread_setrun(b, 0)

    import xnu_sched.scheduler as sched_mod

    old_compute = sched_mod.compute_sched_pri
    try:
        sched_mod.compute_sched_pri = lambda thread, cbg: 10 if thread is a else 50
        sched.sched_tick(125000)
    finally:
        sched_mod.compute_sched_pri = old_compute

    selected, chose_prev = sched.thread_select(proc, 130000, prev_thread=None)
    _assert(
        selected is b and not chose_prev,
        "sched_tick reprioritization should reorder bucket runqueue by new sched_pri",
    )


def test_preempted_thread_keeps_quantum_remainder_on_redispatch() -> None:
    tg = _new_tg("quantum-remainder")
    sched, proc = _new_sched(num_cpus=1)

    low = Thread(thread_group=tg, base_pri=31, name="low")
    hi = Thread(thread_group=tg, base_pri=47, name="hi")

    _dispatch_current(sched, proc, low, ts=0)
    initial_quantum = low.quantum_remaining

    # Emulate preemption after low has consumed part of its quantum.
    preempt_ts = 2000
    _assert(
        sched.thread_setrun(hi, preempt_ts, options=(SCHED_PREEMPT | SCHED_TAILQ)) is proc,
        "higher-priority thread should request preemption",
    )

    consumed = preempt_ts - proc.last_dispatch_time
    low.quantum_remaining = max(0, low.quantum_remaining - consumed)
    expected_remainder = low.quantum_remaining
    low.state = ThreadState.RUNNABLE

    selected, chose_prev = sched.thread_select(proc, preempt_ts, prev_thread=low)
    _assert(selected is hi and not chose_prev, "preemption should select higher-priority thread")

    sched.thread_setrun(low, preempt_ts, options=SCHED_HEADQ)
    sched.thread_dispatch(proc, low, hi, preempt_ts)

    # When hi blocks, low should resume with its remaining quantum, not a reset.
    resumed = sched.thread_block(hi, proc, preempt_ts + 1000)
    _assert(resumed is low, "low thread should resume after higher-priority thread blocks")
    _assert(
        low.quantum_remaining == expected_remainder,
        (
            "preempted thread should keep quantum remainder on redispatch "
            f"(expected {expected_remainder}, got {low.quantum_remaining}, initial {initial_quantum})"
        ),
    )


def test_bound_threads_are_excluded_from_clutch_timeshare_accounting() -> None:
    tg = _new_tg("bound-accounting")
    sched, proc = _new_sched(num_cpus=1)

    bound = Thread(thread_group=tg, base_pri=31, name="bound")
    bound.bound_processor = proc

    clutch = tg.sched_clutch
    _assert(clutch is not None, "thread group should have clutch state")
    cbg = clutch.sc_clutch_groups[bound.th_sched_bucket]

    # Bound threads should ignore clutch pri_shift for timeshare decay.
    cbg.scbg_pri_shift = 1
    bound.cpu_usage = 100
    _assert(
        compute_sched_pri(bound, cbg) == bound.base_pri,
        "bound threads must not decay sched_pri via clutch pri_shift",
    )

    before = cbg.scbg_cpu_used
    update_thread_cpu_usage(bound, 1000, cbg)
    _assert(
        cbg.scbg_cpu_used == before,
        "bound threads must not contribute to clutch bucket-group CPU usage",
    )


def test_timeshare_decay_uses_sched_usage_not_cpu_usage() -> None:
    tg = _new_tg("sched-usage-source")
    t = Thread(thread_group=tg, base_pri=47, name="t")
    clutch = tg.sched_clutch
    _assert(clutch is not None, "thread group should have clutch state")
    cbg = clutch.sc_clutch_groups[t.th_sched_bucket]

    # XNU computes decay from sched_usage, not cpu_usage.
    t.pri_shift = 1
    t.cpu_usage = 1000
    t.sched_usage = 0
    _assert(
        compute_sched_pri(t, cbg) == t.base_pri,
        "timeshare decay must use sched_usage, not cpu_usage",
    )

    # pri_shift == 31 is still a valid decay shift in XNU (only INT8_MAX disables decay).
    t.pri_shift = 31
    t.sched_usage = 1 << 31
    _assert(
        compute_sched_pri(t, cbg) == (t.base_pri - 1),
        "pri_shift 31 should still apply decay (INT8_MAX is the no-decay sentinel)",
    )


def test_sched_usage_charging_respects_pri_shift_and_ages() -> None:
    tg = _new_tg("sched-usage-charge")
    t = Thread(thread_group=tg, base_pri=47, name="t")
    clutch = tg.sched_clutch
    _assert(clutch is not None, "thread group should have clutch state")
    cbg = clutch.sc_clutch_groups[t.th_sched_bucket]

    # No contention: pri_shift == INT8_MAX means no sched_usage charging.
    t.pri_shift = 127
    update_thread_cpu_usage(t, 1000, cbg)
    _assert(
        t.sched_usage == 0,
        "sched_usage should not accumulate when pri_shift is INT8_MAX",
    )
    _assert(t.cpu_usage == 1000, "cpu_usage should still track raw CPU runtime")

    # Contended window: sched_usage should charge and then decay.
    t.pri_shift = 1
    update_thread_cpu_usage(t, 8, cbg)
    _assert(
        t.sched_usage == 8,
        "sched_usage should accumulate CPU time when pri_shift is finite",
    )
    _assert(
        compute_sched_pri(t, cbg) == (t.base_pri - 4),
        "sched_pri decay should follow sched_usage >> pri_shift",
    )

    age_thread_cpu_usage(t)
    _assert(
        t.sched_usage == 5,
        "sched_usage aging should use the same 5/8 decay as cpu_usage",
    )
    _assert(
        compute_sched_pri(t, cbg) == (t.base_pri - 2),
        "aged sched_usage should feed through into reduced decay",
    )


def test_setrun_ages_waiting_timeshare_usage_before_enqueue() -> None:
    tg = _new_tg("setrun-age")
    sched, _ = _new_sched(num_cpus=1)

    t = Thread(thread_group=tg, base_pri=47, name="sleeper")
    clutch = tg.sched_clutch
    _assert(clutch is not None, "thread group should have clutch state")
    cbg = clutch.sc_clutch_groups[t.th_sched_bucket]

    # Seed prior CPU penalty and finite pri_shift as if the thread previously ran
    # in a contended interval, then blocked.
    t.state = ThreadState.WAITING
    t.sched_usage = 64
    t.cpu_usage = 64
    t.pri_shift = 1
    t.sched_stamp = 0
    cbg.scbg_pri_shift = 1

    # Advance scheduler ticks while the thread is sleeping.
    sched.sched_tick(125000)
    sched.sched_tick(250000)
    sched.sched_tick(375000)
    _assert(sched.current_tick == 3, "expected 3 elapsed scheduler ticks")

    # Sleeping thread isn't in runnable queue scans, so aging should happen when
    # it is made runnable again via thread_setrun().
    _assert(t.sched_usage == 64, "waiting thread should not age in runnable scan path")

    sched.thread_setrun(t, 400000, options=SCHED_TAILQ)
    _assert(
        t.sched_stamp == 3,
        "thread_setrun should advance sched_stamp to current sched_tick",
    )
    _assert(
        t.sched_usage == 16,
        "thread_setrun should age waiting-thread sched_usage for elapsed ticks",
    )
    _assert(
        t.sched_pri == 39,
        "thread_setrun should recompute sched_pri after aging stale usage",
    )


def test_decay_uses_xnu_shift_table_not_exact_5_over_8_floor() -> None:
    tg = _new_tg("decay-shift-table")
    t = Thread(thread_group=tg, base_pri=47, name="t")

    # For ticks=1 XNU uses (usage >> 1) + (usage >> 3), which differs from
    # floor(usage * 5 / 8) for some values (e.g., 7 -> 3 vs 4).
    t.cpu_usage = 7
    t.sched_usage = 7
    age_thread_cpu_usage(t, decay_factor=1)
    _assert(
        t.cpu_usage == 3 and t.sched_usage == 3,
        "decay should follow XNU shift-table semantics (7 -> 3 at one tick)",
    )


def test_decay_ticks_at_limit_zero_usage() -> None:
    tg = _new_tg("decay-limit")
    t = Thread(thread_group=tg, base_pri=47, name="t")
    t.cpu_usage = 1 << 20
    t.sched_usage = 1 << 19
    age_thread_cpu_usage(t, decay_factor=32)
    _assert(
        t.cpu_usage == 0 and t.sched_usage == 0,
        "ticks >= SCHED_DECAY_TICKS should clear accumulated usage",
    )


def test_quantum_expire_ages_running_thread_when_tick_advanced() -> None:
    tg = _new_tg("quantum-age-running")
    sched, proc = _new_sched(num_cpus=1)

    t = Thread(thread_group=tg, base_pri=47, name="runner")
    _dispatch_current(sched, proc, t, ts=0)

    clutch = tg.sched_clutch
    _assert(clutch is not None, "thread group should have clutch state")
    cbg = clutch.sc_clutch_groups[t.th_sched_bucket]

    t.sched_usage = 64
    t.cpu_usage = 64
    t.pri_shift = 1
    t.sched_stamp = 0
    cbg.scbg_pri_shift = 1

    # Simulate maintenance tick advancing while this thread remains running.
    sched.current_tick = 1
    t.computation_epoch = 1
    next_thread = sched.thread_quantum_expire(proc, 1)

    _assert(next_thread is t, "single runnable thread should keep running")
    _assert(
        t.sched_stamp == 1,
        "quantum-expire path should apply update_priority-style tick aging",
    )
    _assert(
        t.sched_usage == 40,
        "running thread should age sched_usage when sched_tick has advanced",
    )
    _assert(
        t.sched_pri == 27,
        "aged running-thread usage should feed through into sched_pri",
    )


def test_preemption_path_ages_running_thread_when_tick_advanced() -> None:
    tg = _new_tg("preempt-age-running")
    engine = SimulationEngine(num_cpus=1, trace=False)
    sched = engine.scheduler
    proc = sched.pset.processors[0]

    t = Thread(thread_group=tg, base_pri=47, name="runner")
    sched.thread_dispatch(proc, None, t, 1000)

    clutch = tg.sched_clutch
    _assert(clutch is not None, "thread group should have clutch state")
    cbg = clutch.sc_clutch_groups[t.th_sched_bucket]

    t.sched_usage = 64
    t.cpu_usage = 64
    t.pri_shift = 1
    t.sched_stamp = 0
    cbg.scbg_pri_shift = 1

    # Emulate a preemption AST after sched_tick advanced, with no runnable peer.
    # XNU thread_select() still updates current-thread priority in this path.
    sched.current_tick = 1
    engine.clock = 1000
    engine._handle_preemption(proc)

    _assert(proc.active_thread is t, "single runnable thread should keep running")
    _assert(
        t.sched_stamp == 1,
        "preemption path should apply update_priority-style tick aging",
    )
    _assert(
        t.sched_usage == 40,
        "preemption path should age sched_usage when sched_tick has advanced",
    )
    _assert(
        t.sched_pri == 27,
        "aged preemption-path usage should feed through into sched_pri",
    )


def test_rt_quantum_uses_rt_computation_budget() -> None:
    tg = _new_tg("rt-quantum")
    engine = SimulationEngine(num_cpus=1, trace=False)
    sched = engine.scheduler
    proc = sched.pset.processors[0]

    rt = _new_rt_thread(
        tg,
        "rt",
        BASEPRI_RTQUEUES + 1,
        deadline=1000,
        computation=750,
        constraint=5000,
    )
    rt.quantum_remaining = 0
    sched.thread_dispatch(proc, None, rt, 0)
    _assert(
        rt.quantum_remaining == 750,
        "RT dispatch should initialize quantum from rt_computation",
    )

    engine.clock = 0
    engine._schedule_quantum_expire(proc, rt)
    _assert(
        proc.quantum_end == 750,
        "engine quantum timer should use RT computation budget",
    )


def test_stale_quantum_expire_event_is_ignored() -> None:
    tg = _new_tg("stale-quantum")
    engine = SimulationEngine(num_cpus=1, trace=False)
    sched = engine.scheduler
    proc = sched.pset.processors[0]

    t = Thread(thread_group=tg, base_pri=31, name="t")
    sched.thread_dispatch(proc, None, t, 0)

    engine.clock = 0
    t.quantum_remaining = 1000
    engine._schedule_quantum_expire(proc, t)
    stale_expire = proc.quantum_end

    engine.clock = 100
    t.quantum_remaining = 2000
    engine._schedule_quantum_expire(proc, t)
    current_expire = proc.quantum_end

    stale = Event(
        timestamp=stale_expire,
        event_type=EventType.QUANTUM_EXPIRE,
        thread_id=t.tid,
        processor_id=proc.processor_id,
    )
    engine.clock = stale_expire
    engine._handle_quantum_expire(stale)

    _assert(
        proc.active_thread is t and proc.quantum_end == current_expire,
        "stale quantum-expire event must not fire after a newer quantum timer was armed",
    )


def test_stale_thread_block_event_is_ignored() -> None:
    tg = _new_tg("stale-thread-block")
    engine = SimulationEngine(num_cpus=1, trace=False)
    sched = engine.scheduler
    proc = sched.pset.processors[0]

    t = Thread(thread_group=tg, base_pri=31, name="t")
    sched.all_threads.append(t)
    sched.thread_dispatch(proc, None, t, 0)

    behavior = BehaviorProfile(avg_cpu_burst_us=1000, avg_block_duration_us=1000)
    bursts = iter([1000, 2000])
    behavior.sample_cpu_burst = lambda: next(bursts)  # type: ignore[assignment]
    engine.thread_behaviors[t.tid] = behavior

    engine.clock = 0
    engine._schedule_thread_block(t)
    stale_block_ts = 1000

    # Thread is preempted and later redispatched with a new CPU burst budget.
    engine.clock = 200
    engine._schedule_thread_block(t)
    current_block_ts = 2200

    stale = Event(
        timestamp=stale_block_ts,
        event_type=EventType.THREAD_BLOCK,
        thread_id=t.tid,
    )
    engine.clock = stale_block_ts
    engine._handle_thread_block(stale)
    _assert(
        proc.active_thread is t and t.state == ThreadState.RUNNING,
        "stale thread-block event must not block a thread after a newer block deadline was armed",
    )

    current = Event(
        timestamp=current_block_ts,
        event_type=EventType.THREAD_BLOCK,
        thread_id=t.tid,
    )
    engine.clock = current_block_ts
    engine._handle_thread_block(current)
    _assert(
        t.state == ThreadState.WAITING,
        "current thread-block event should still block the running thread",
    )


def test_block_dispatch_reschedules_block_deadline_and_clears_missed_deadline() -> None:
    tg = _new_tg("block-dispatch-reschedule")
    engine = SimulationEngine(num_cpus=1, trace=False)
    sched = engine.scheduler
    proc = sched.pset.processors[0]

    running = Thread(thread_group=tg, base_pri=40, name="running")
    next_thread = Thread(thread_group=tg, base_pri=30, name="next")
    sched.all_threads.extend([running, next_thread])
    sched.thread_dispatch(proc, None, running, 0)
    sched.thread_setrun(next_thread, 1, options=SCHED_TAILQ)

    next_behavior = BehaviorProfile(avg_cpu_burst_us=1000, avg_block_duration_us=1000)
    next_behavior.sample_cpu_burst = lambda: 700  # type: ignore[assignment]
    engine.thread_behaviors[next_thread.tid] = next_behavior

    # If a block timer fires while the thread is off-core, its armed deadline
    # should be discarded instead of lingering and firing on a later dispatch.
    engine._thread_block_deadlines[next_thread.tid] = 50
    missed = Event(
        timestamp=50,
        event_type=EventType.THREAD_BLOCK,
        thread_id=next_thread.tid,
    )
    engine.clock = 50
    engine._handle_thread_block(missed)
    _assert(
        next_thread.tid not in engine._thread_block_deadlines,
        "missed off-core block deadline should be cleared",
    )

    # When a thread is dispatched due to another thread blocking, it must arm
    # a fresh block deadline for its new dispatch slice.
    engine._thread_block_deadlines[running.tid] = 100
    block_running = Event(
        timestamp=100,
        event_type=EventType.THREAD_BLOCK,
        thread_id=running.tid,
    )
    engine.clock = 100
    engine._handle_thread_block(block_running)

    _assert(
        proc.active_thread is next_thread and next_thread.state == ThreadState.RUNNING,
        "next runnable thread should be dispatched when current thread blocks",
    )
    fresh_deadline = engine._thread_block_deadlines.get(next_thread.tid)
    _assert(
        fresh_deadline is not None and fresh_deadline > 100,
        "dispatch-on-block must arm a fresh block deadline for the new running thread",
    )


def test_rt_quantum_expire_marks_deadline_expired_for_reschedule() -> None:
    tg = _new_tg("rt-deadline-expire")
    sched, proc = _new_sched(num_cpus=1)

    prev = _new_rt_thread(
        tg, "prev", BASEPRI_RTQUEUES + 2, deadline=1000, computation=500, constraint=10000
    )
    queued = _new_rt_thread(
        tg, "queued", BASEPRI_RTQUEUES + 2, deadline=2000, computation=500, constraint=10000
    )

    _dispatch_current(sched, proc, prev, ts=0)
    sched.thread_setrun(queued, 10)

    selected = sched.thread_quantum_expire(proc, 500)
    _assert(
        prev.rt_deadline == RT_DEADLINE_QUANTUM_EXPIRED,
        "RT quantum expiry should mark current thread deadline as quantum-expired",
    )
    _assert(
        selected is queued,
        "expired RT thread should not keep running ahead of queued RT peer",
    )


def test_rt_wakeup_recomputes_deadline_from_constraint() -> None:
    tg = _new_tg("rt-wakeup-deadline")
    sched, _ = _new_sched(num_cpus=1)

    t = _new_rt_thread(
        tg, "rt", BASEPRI_RTQUEUES + 1, deadline=1234, computation=300, constraint=5000
    )
    t.state = ThreadState.WAITING
    t.rt_deadline = RT_DEADLINE_QUANTUM_EXPIRED

    sched.thread_wakeup(t, 2000)
    _assert(
        t.rt_deadline == 7000,
        "RT wakeup should assign deadline = now + rt_constraint",
    )


def test_rt_setrun_assigns_deadline_when_none() -> None:
    tg = _new_tg("rt-deadline-none")
    sched, _ = _new_sched(num_cpus=1)

    t = _new_rt_thread(
        tg, "rt-none", BASEPRI_RTQUEUES + 1, deadline=RT_DEADLINE_NONE, computation=300, constraint=5000
    )
    t.state = ThreadState.WAITING

    sched.thread_setrun(t, 1200)
    _assert(
        t.rt_deadline == 6200,
        "RT enqueue should assign deadline = now + rt_constraint when deadline is NONE",
    )


def test_setrun_same_tick_does_not_recompute_timeshare_priority() -> None:
    tg = _new_tg("setrun-same-tick")
    sched, _ = _new_sched(num_cpus=1)

    t = Thread(thread_group=tg, base_pri=47, name="same-tick")
    clutch = tg.sched_clutch
    _assert(clutch is not None, "thread group should have clutch state")
    cbg = clutch.sc_clutch_groups[t.th_sched_bucket]

    t.state = ThreadState.WAITING
    t.sched_pri = 47
    t.sched_usage = 512
    t.cpu_usage = 512
    t.pri_shift = 1
    t.sched_stamp = 0
    cbg.scbg_pri_shift = 1

    # No sched_tick advancement: can_update_priority() would be false in XNU,
    # so thread_setrun should not refresh sched_pri from sched_usage yet.
    _assert(sched.current_tick == 0, "expected initial sched_tick to be zero")
    sched.thread_setrun(t, 1, options=SCHED_TAILQ)
    _assert(
        t.sched_pri == 47,
        "same-tick thread_setrun should not recompute timeshare sched_pri",
    )


def test_non_tailq_enqueue_is_treated_as_preempted_headq() -> None:
    tg = _new_tg("non-tailq-preempted")

    # Clutch queue path
    sched, proc = _new_sched(num_cpus=1)
    tail = Thread(thread_group=tg, base_pri=31, name="tail")
    preemptish = Thread(thread_group=tg, base_pri=31, name="preemptish")
    sched.thread_setrun(tail, 0, options=SCHED_TAILQ)
    sched.thread_setrun(preemptish, 1, options=SCHED_PREEMPT)
    selected, chose_prev = sched.thread_select(proc, 2, prev_thread=None)
    _assert(
        selected is preemptish and not chose_prev,
        "non-TAILQ clutch enqueue should behave as preempted/head insertion",
    )

    # Bound queue path
    sched, proc = _new_sched(num_cpus=1)
    b_tail = Thread(thread_group=tg, base_pri=31, name="b-tail")
    b_preemptish = Thread(thread_group=tg, base_pri=31, name="b-preemptish")
    b_tail.bound_processor = proc
    b_preemptish.bound_processor = proc
    sched.thread_setrun(b_tail, 0, options=SCHED_TAILQ)
    sched.thread_setrun(b_preemptish, 1, options=SCHED_PREEMPT)
    selected, chose_prev = sched.thread_select(proc, 2, prev_thread=None)
    _assert(
        selected is b_preemptish and not chose_prev,
        "non-TAILQ bound enqueue should behave as head insertion",
    )


def test_wakeup_uses_preempt_tailq_ordering() -> None:
    tg = _new_tg("wakeup-tailq")
    sched, proc = _new_sched(num_cpus=1)

    first = Thread(thread_group=tg, base_pri=31, name="first")
    second = Thread(thread_group=tg, base_pri=31, name="second")

    # XNU wakeups enqueue with PREEMPT|TAILQ (non-preempted stable ordering),
    # so older wakeups should be selected first at equal priority.
    sched.thread_wakeup(first, 0)
    sched.thread_wakeup(second, 1)
    selected, chose_prev = sched.thread_select(proc, 2, prev_thread=None)
    _assert(
        selected is first and not chose_prev,
        "wakeup path should preserve FIFO order for equal-priority peers",
    )


def test_clutch_run_count_tracks_running_plus_runnable_not_runqueue_only() -> None:
    tg = _new_tg("run-count")
    sched, proc = _new_sched(num_cpus=1)

    t = Thread(thread_group=tg, base_pri=31, name="t")
    clutch = tg.sched_clutch
    _assert(clutch is not None, "thread group should have clutch state")
    cbg = clutch.sc_clutch_groups[t.th_sched_bucket]

    # Wakeup transitions WAITING -> RUNNABLE: run_count increments.
    sched.thread_setrun(t, 0, options=SCHED_TAILQ)
    _assert(cbg.scbg_blocked_count == 1, "run_count should increment on wakeup")

    # Selecting/removing from runqueue to RUNNING must NOT decrement run_count.
    selected, chose_prev = sched.thread_select(proc, 1, prev_thread=None)
    _assert(selected is t and not chose_prev, "thread should be selected")
    sched.thread_dispatch(proc, None, t, 1)
    _assert(
        cbg.scbg_blocked_count == 1,
        "run_count should include running thread even when runqueue is empty",
    )

    # Blocking RUNNING -> WAITING decrements run_count.
    sched.thread_block(t, proc, 2)
    _assert(cbg.scbg_blocked_count == 0, "run_count should decrement on block")


def test_preemption_reenqueue_does_not_double_increment_run_count() -> None:
    tg = _new_tg("run-count-preempt")
    sched, proc = _new_sched(num_cpus=1)

    low = Thread(thread_group=tg, base_pri=31, name="low")
    peer = Thread(thread_group=tg, base_pri=31, name="peer")
    clutch = tg.sched_clutch
    _assert(clutch is not None, "thread group should have clutch state")
    cbg = clutch.sc_clutch_groups[low.th_sched_bucket]

    sched.thread_setrun(low, 0, options=SCHED_TAILQ)   # WAITING->RUNNABLE
    selected, _ = sched.thread_select(proc, 1, prev_thread=None)
    _assert(selected is low, "low should be selected first")
    sched.thread_dispatch(proc, None, low, 1)          # low now RUNNING
    _assert(cbg.scbg_blocked_count == 1, "run_count should be 1 with one running thread")

    sched.thread_setrun(peer, 2, options=SCHED_TAILQ)  # WAITING->RUNNABLE
    _assert(cbg.scbg_blocked_count == 2, "run_count should be 2 after peer wakeup")

    # Simulate preemption path: low transitions RUNNING->RUNNABLE and is re-enqueued.
    low.state = ThreadState.RUNNABLE
    sched.thread_setrun(low, 3, options=SCHED_HEADQ)
    _assert(
        cbg.scbg_blocked_count == 2,
        "re-enqueue of already-runnable thread must not increment run_count",
    )


def test_sched_tick_updates_clutch_bucket_priority_for_interactivity_changes() -> None:
    tg1 = _new_tg("tick-cb-pri-1")
    tg2 = _new_tg("tick-cb-pri-2")
    sched, proc = _new_sched(num_cpus=1)

    t1 = Thread(thread_group=tg1, base_pri=31, name="t1")
    t2 = Thread(thread_group=tg2, base_pri=31, name="t2")
    sched.thread_setrun(t1, 0, options=SCHED_TAILQ)
    sched.thread_setrun(t2, 0, options=SCHED_TAILQ)

    cbg1 = tg1.sched_clutch.sc_clutch_groups[t1.th_sched_bucket]  # type: ignore[union-attr]
    cbg2 = tg2.sched_clutch.sc_clutch_groups[t2.th_sched_bucket]  # type: ignore[union-attr]

    import xnu_sched.clutch as clutch_mod

    old_interactivity = clutch_mod.SchedClutchBucketGroup.interactivity_score_calculate
    try:
        def fake_interactivity(self, timestamp: int, global_bucket_load: int = 0) -> int:
            if self is cbg1:
                return 0
            if self is cbg2:
                return 16
            return old_interactivity(self, timestamp, global_bucket_load)

        clutch_mod.SchedClutchBucketGroup.interactivity_score_calculate = fake_interactivity
        sched.sched_tick(125000)
    finally:
        clutch_mod.SchedClutchBucketGroup.interactivity_score_calculate = old_interactivity

    selected, chose_prev = sched.thread_select(proc, 130000, prev_thread=None)
    _assert(
        selected is t2 and not chose_prev,
        "sched_tick should refresh clutch-bucket priority from interactivity updates",
    )


def test_block_clears_quantum_for_wakeup() -> None:
    tg = _new_tg("block-quantum")
    sched, proc = _new_sched(num_cpus=1)

    t = Thread(thread_group=tg, base_pri=31, name="t")
    sched.thread_setrun(t, 0, options=SCHED_TAILQ)
    selected, chose_prev = sched.thread_select(proc, 1, prev_thread=None)
    _assert(selected is t and not chose_prev, "thread should dispatch")
    sched.thread_dispatch(proc, None, t, 1)

    block_ts = 2001
    sched.thread_block(t, proc, block_ts)

    _assert(
        t.quantum_remaining == 0,
        "block/wait path should clear saved quantum before wakeup",
    )

    # Wake and re-dispatch should allocate a fresh quantum.
    sched.thread_wakeup(t, 3000)
    selected, chose_prev = sched.thread_select(proc, 3001, prev_thread=None)
    _assert(selected is t and not chose_prev, "woken thread should be selected")
    sched.thread_dispatch(proc, None, t, 3001)
    _assert(
        t.quantum_remaining > 0,
        "wakeup redispatch should start with a fresh positive quantum",
    )


def run() -> int:
    tests: list[tuple[str, callable]] = [
        ("stable_runqueue_ordering", test_stable_runqueue_ordering),
        ("rt_runqueue_policy", test_rt_runqueue_policy),
        ("rt_prev_thread_keep_running_and_preempt", test_rt_prev_thread_keep_running_and_preempt),
        ("rt_higher_priority_constraint_gate", test_rt_higher_priority_constraint_gate),
        ("rt_non_first_timeslice_forces_pick_from_runq", test_rt_non_first_timeslice_forces_pick_from_runq),
        ("rt_setrun_non_first_timeslice_does_not_preempt_without_better_rt", test_rt_setrun_non_first_timeslice_does_not_preempt_without_better_rt),
        ("bound_prev_not_considered_in_clutch_hierarchy", test_bound_prev_not_considered_in_clutch_hierarchy),
        ("bound_queue_tie_breaks_over_clutch", test_bound_queue_tie_breaks_over_clutch),
        ("root_priority_uses_raw_thread_pri_not_interactivity", test_root_priority_uses_raw_thread_pri_not_interactivity),
        ("bound_preemption_targets_bound_cpu", test_bound_preemption_targets_bound_cpu),
        ("non_preempt_enqueue_does_not_force_nonurgent_cross_cpu_preempt", test_non_preempt_enqueue_does_not_force_nonurgent_cross_cpu_preempt),
        ("non_preempt_enqueue_still_preempts_for_urgent_priority", test_non_preempt_enqueue_still_preempts_for_urgent_priority),
        ("equal_priority_preempt_requires_preempt_option_and_non_first_timeslice", test_equal_priority_preempt_requires_preempt_option_and_non_first_timeslice),
        ("equal_urgent_priority_without_preempt_does_not_preempt", test_equal_urgent_priority_without_preempt_does_not_preempt),
        ("equal_priority_with_preempt_still_signals_on_first_timeslice", test_equal_priority_with_preempt_still_signals_on_first_timeslice),
        ("rt_higher_pri_safe_does_not_preempt_by_deadline_fallthrough", test_rt_higher_pri_safe_does_not_preempt_by_deadline_fallthrough),
        ("sched_tick_refreshes_thread_runq_after_priority_changes", test_sched_tick_refreshes_thread_runq_after_priority_changes),
        ("preempted_thread_keeps_quantum_remainder_on_redispatch", test_preempted_thread_keeps_quantum_remainder_on_redispatch),
        ("bound_threads_are_excluded_from_clutch_timeshare_accounting", test_bound_threads_are_excluded_from_clutch_timeshare_accounting),
        ("timeshare_decay_uses_sched_usage_not_cpu_usage", test_timeshare_decay_uses_sched_usage_not_cpu_usage),
        ("sched_usage_charging_respects_pri_shift_and_ages", test_sched_usage_charging_respects_pri_shift_and_ages),
        ("setrun_ages_waiting_timeshare_usage_before_enqueue", test_setrun_ages_waiting_timeshare_usage_before_enqueue),
        ("decay_uses_xnu_shift_table_not_exact_5_over_8_floor", test_decay_uses_xnu_shift_table_not_exact_5_over_8_floor),
        ("decay_ticks_at_limit_zero_usage", test_decay_ticks_at_limit_zero_usage),
        ("quantum_expire_ages_running_thread_when_tick_advanced", test_quantum_expire_ages_running_thread_when_tick_advanced),
        ("preemption_path_ages_running_thread_when_tick_advanced", test_preemption_path_ages_running_thread_when_tick_advanced),
        ("rt_quantum_uses_rt_computation_budget", test_rt_quantum_uses_rt_computation_budget),
        ("stale_quantum_expire_event_is_ignored", test_stale_quantum_expire_event_is_ignored),
        ("stale_thread_block_event_is_ignored", test_stale_thread_block_event_is_ignored),
        ("block_dispatch_reschedules_block_deadline_and_clears_missed_deadline", test_block_dispatch_reschedules_block_deadline_and_clears_missed_deadline),
        ("rt_quantum_expire_marks_deadline_expired_for_reschedule", test_rt_quantum_expire_marks_deadline_expired_for_reschedule),
        ("rt_wakeup_recomputes_deadline_from_constraint", test_rt_wakeup_recomputes_deadline_from_constraint),
        ("rt_setrun_assigns_deadline_when_none", test_rt_setrun_assigns_deadline_when_none),
        ("setrun_same_tick_does_not_recompute_timeshare_priority", test_setrun_same_tick_does_not_recompute_timeshare_priority),
        ("non_tailq_enqueue_is_treated_as_preempted_headq", test_non_tailq_enqueue_is_treated_as_preempted_headq),
        ("wakeup_uses_preempt_tailq_ordering", test_wakeup_uses_preempt_tailq_ordering),
        ("clutch_run_count_tracks_running_plus_runnable_not_runqueue_only", test_clutch_run_count_tracks_running_plus_runnable_not_runqueue_only),
        ("preemption_reenqueue_does_not_double_increment_run_count", test_preemption_reenqueue_does_not_double_increment_run_count),
        ("sched_tick_updates_clutch_bucket_priority_for_interactivity_changes", test_sched_tick_updates_clutch_bucket_priority_for_interactivity_changes),
        ("block_clears_quantum_for_wakeup", test_block_clears_quantum_for_wakeup),
    ]
    passed = 0
    failed = 0

    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"[PASS] {name}")
        except Exception as exc:  # noqa: BLE001 - explicit harness output
            failed += 1
            print(f"[FAIL] {name}: {exc}")

    print(f"\nSummary: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
