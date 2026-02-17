"""
Core scheduler: orchestrates the Clutch hierarchy, RT queue, and processors.

Ports the key scheduling paths from XNU:
  - thread_setrun (enqueue): sched_clutch.c thread_insert path
  - thread_select (dequeue): hierarchy_thread_highest + RT comparison
  - thread_dispatch: context switch, quantum management
  - sched_tick: periodic maintenance

This is the central coordinator that the simulation engine calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .constants import (
    TH_MODE_REALTIME,
    TH_MODE_FIXED,
    TH_MODE_TIMESHARE,
    TH_BUCKET_FIXPRI,
    TH_BUCKET_SCHED_MAX,
    BASEPRI_RTQUEUES,
    BASEPRI_PREEMPT,
    THREAD_QUANTUM_US,
    SCHED_HEADQ,
    SCHED_TAILQ,
    SCHED_PREEMPT,
    SCHED_CLUTCH_BUCKET_OPTIONS_HEADQ,
    SCHED_CLUTCH_BUCKET_OPTIONS_TAILQ,
    SCHED_CLUTCH_BUCKET_OPTIONS_NONE,
    SCHED_CLUTCH_BUCKET_OPTIONS_SAMEPRI_RR,
    SCHED_TICK_INTERVAL_US,
    NOPRI,
    RT_DEADLINE_QUANTUM_EXPIRED,
    RT_DEADLINE_NONE,
    is_above_timeshare,
)
from .thread import Thread, ThreadState, thread_bucket_map
from .clutch import SchedClutch, SchedClutchBucket, SchedClutchBucketGroup
from .clutch_root import ClutchRoot
from .priority_queue import StablePriorityQueue
from .processor import Processor, ProcessorSet, ProcessorState
from .rt_queue import RTQueue
from .timeshare import compute_sched_pri, update_thread_cpu_usage, age_thread_cpu_usage

if TYPE_CHECKING:
    pass


class Scheduler:
    """Core Clutch scheduler orchestrating all components."""

    __slots__ = (
        "pset",
        "current_tick",
        "all_threads",
        "all_thread_groups",
        "trace_enabled",
        "trace_log",
        "processor_switch_log",
        "_pending_preemption_reason",
        "_bound_runqs",
        # Callbacks for simulation engine
        "_on_preemption",
    )

    def __init__(self, pset: ProcessorSet, trace: bool = False) -> None:
        self.pset = pset
        self.current_tick: int = 0
        self.all_threads: list[Thread] = []
        self.all_thread_groups: list = []
        self.trace_enabled = trace
        self.trace_log: list[str] = []
        self.processor_switch_log: list[str] = []
        self._pending_preemption_reason: dict[int, str] = {}
        self._bound_runqs: list[StablePriorityQueue[Thread]] = [
            StablePriorityQueue(lambda t: t.sched_pri)
            for _ in self.pset.processors
        ]
        self._on_preemption = None

    def _trace(self, timestamp: int, msg: str) -> None:
        if self.trace_enabled:
            self.trace_log.append(f"[{timestamp:>10}us] {msg}")

    def _log_processor_switch(
        self,
        timestamp: int,
        processor: Processor,
        old_thread: Thread | None,
        new_thread: Thread | None,
        reason: str,
    ) -> None:
        """Record a CPU run-target change (including transitions to idle)."""
        if old_thread is new_thread:
            return
        old_name = old_thread.name if old_thread is not None else "idle"
        new_name = new_thread.name if new_thread is not None else "idle"
        self.processor_switch_log.append(
            f"[{timestamp:>10}us] CPU{processor.processor_id}: {old_name} -> {new_name} | reason: {reason}"
        )

    def _set_preemption_reason(self, processor: Processor, reason: str) -> None:
        self._pending_preemption_reason[processor.processor_id] = reason

    def consume_preemption_reason(self, processor: Processor) -> str:
        """Consume the pending preemption/dispatch reason for a processor."""
        return self._pending_preemption_reason.pop(
            processor.processor_id,
            "runnable thread became eligible for this processor",
        )

    @property
    def clutch_root(self) -> ClutchRoot:
        return self.pset.clutch_root

    @property
    def rt_runq(self) -> RTQueue:
        return self.pset.rt_runq

    @staticmethod
    def _pri_greater_tiebreak(pri_one: int, pri_two: int, one_wins_ties: bool) -> bool:
        if one_wins_ties:
            return pri_one >= pri_two
        return pri_one > pri_two

    def _bound_runq(self, processor: Processor) -> StablePriorityQueue[Thread]:
        return self._bound_runqs[processor.processor_id]

    def _timeshare_setrun_update(self, thread: Thread) -> None:
        """Mirror XNU's thread_setrun() update_priority() behavior for timeshare threads."""
        clutch = thread.thread_group.sched_clutch
        if clutch is None:
            return

        cbg = clutch.sc_clutch_groups[thread.th_sched_bucket]
        elapsed_ticks = max(0, self.current_tick - thread.sched_stamp)
        if elapsed_ticks == 0:
            # Mirrors can_update_priority()==FALSE in thread_setrun():
            # no update_priority path on the same sched_tick.
            return

        age_thread_cpu_usage(thread, decay_factor=elapsed_ticks)
        thread.sched_stamp = self.current_tick

        # Non-clutch-eligible (bound) threads use INT8_MAX in XNU.
        if thread.bound_processor is not None:
            thread.pri_shift = 127
        else:
            thread.pri_shift = cbg.scbg_pri_shift

        thread.sched_pri = compute_sched_pri(thread, cbg)

    # ------------------------------------------------------------------
    # Thread enqueue (thread_setrun path)
    # Ports sched_clutch_thread_insert() (sched_clutch.c:2721-2794)
    # ------------------------------------------------------------------
    def thread_setrun(
        self, thread: Thread, timestamp: int, options: int = SCHED_TAILQ
    ) -> Processor | None:
        """Enqueue a thread that has become runnable.

        Returns a processor to signal for preemption, or None.
        """
        old_state = thread.state
        thread.state = ThreadState.RUNNABLE
        thread.last_made_runnable_time = timestamp
        became_runnable = old_state not in (ThreadState.RUNNABLE, ThreadState.RUNNING)

        if thread.is_timeshare:
            self._timeshare_setrun_update(thread)

        if thread.is_realtime:
            return self._rt_thread_setrun(thread, timestamp)

        if thread.bound_processor is not None:
            return self._bound_thread_setrun(thread, timestamp, options)

        return self._clutch_thread_setrun(
            thread, timestamp, options, became_runnable=became_runnable
        )

    def _rt_thread_setrun(
        self, thread: Thread, timestamp: int
    ) -> Processor | None:
        """Enqueue an RT thread into the RT deadline queue."""
        if thread.rt_deadline == RT_DEADLINE_NONE:
            thread.rt_deadline = timestamp + thread.rt_constraint

        self.rt_runq.enqueue(thread)
        self._trace(timestamp, f"RT enqueue: {thread.name} deadline={thread.rt_deadline}")

        # Check for preemption: RT always preempts non-RT
        return self._check_preemption(thread, timestamp, options=SCHED_PREEMPT)

    def _clutch_thread_setrun(
        self,
        thread: Thread,
        timestamp: int,
        options: int,
        became_runnable: bool,
    ) -> Processor | None:
        """Enqueue a timeshare/fixed thread into the Clutch hierarchy.

        Ports sched_clutch_thread_insert().
        """
        clutch = thread.thread_group.sched_clutch
        if clutch is None:
            return None

        cbg = clutch.sc_clutch_groups[thread.th_sched_bucket]
        cb = cbg.scbg_clutch_buckets[self.clutch_root.scr_cluster_id]

        # XNU run_count tracks runnable+running population (TH_RUN), not runqueue
        # membership. Only increment on non-runnable -> runnable transitions.
        if became_runnable:
            cbg.run_count_inc(timestamp)
        clutch.sc_thr_count += 1
        cbg.thr_count_inc(timestamp)

        # Insert thread into clutch bucket thread runqueue
        # XNU stable runqueue marks entries as PREEMPTED unless SCHED_TAILQ is set.
        preempted = not bool(options & SCHED_TAILQ)
        cb.scb_thread_runq.insert(thread, preempted=preempted, stamp=timestamp)

        # Insert into clutchpri queue (for base_pri calculation)
        cb.scb_clutchpri_prioq.insert(thread)

        # Insert into timeshare list
        cb.scb_timeshare_threads.append(thread)

        # Update urgency
        if thread.sched_pri >= BASEPRI_RTQUEUES:
            self.clutch_root.scr_urgency += 1

        # Handle clutch bucket becoming runnable or updating
        scb_options = (
            SCHED_CLUTCH_BUCKET_OPTIONS_HEADQ
            if (options & SCHED_HEADQ)
            else SCHED_CLUTCH_BUCKET_OPTIONS_TAILQ
        )

        if cb.scb_thr_count == 0:
            cb.scb_thr_count += 1
            self.clutch_root.scr_thr_count += 1
            self.clutch_root.clutch_bucket_runnable(cb, timestamp, scb_options)
        else:
            cb.scb_thr_count += 1
            self.clutch_root.scr_thr_count += 1
            self.clutch_root.clutch_bucket_update(cb, timestamp, scb_options)

        self._trace(
            timestamp,
            f"Enqueue: {thread.name} -> {cb} (options={'HEAD' if preempted else 'TAIL'})",
        )

        return self._check_preemption(thread, timestamp, options=options)

    def _bound_thread_setrun(
        self, thread: Thread, timestamp: int, options: int
    ) -> Processor | None:
        """Enqueue a processor-bound non-RT thread on its target processor runqueue."""
        target = thread.bound_processor
        if target is None:
            return None

        # Bound runqueue follows run_queue_enqueue semantics: non-TAILQ inserts at head.
        preempted = not bool(options & SCHED_TAILQ)
        self._bound_runq(target).insert(thread, preempted=preempted, stamp=timestamp)
        self._trace(
            timestamp,
            f"Enqueue bound: {thread.name} -> CPU{target.processor_id} "
            f"(options={'HEAD' if preempted else 'TAIL'})",
        )
        return self._check_preemption(thread, timestamp, options=options)

    # ------------------------------------------------------------------
    # Thread dequeue (thread_remove path)
    # Ports sched_clutch_thread_remove() (sched_clutch.c:2803-2858)
    # ------------------------------------------------------------------
    def thread_remove(self, thread: Thread, timestamp: int) -> None:
        """Remove a thread from the runqueue (it was selected to run or blocked)."""
        if thread.is_realtime:
            self.rt_runq.remove(thread)
            return

        if thread.bound_processor is not None:
            self._bound_runq(thread.bound_processor).remove(thread)
            return

        clutch = thread.thread_group.sched_clutch
        if clutch is None:
            return

        cbg = clutch.sc_clutch_groups[thread.th_sched_bucket]
        cb = cbg.scbg_clutch_buckets[self.clutch_root.scr_cluster_id]

        if cb.scb_root is None:
            return

        # Update urgency
        if thread.sched_pri >= BASEPRI_RTQUEUES:
            self.clutch_root.scr_urgency -= 1

        # Remove from runqueues
        cb.scb_thread_runq.remove(thread)
        if thread in cb.scb_timeshare_threads:
            cb.scb_timeshare_threads.remove(thread)
        cb.scb_clutchpri_prioq.remove(thread)

        # Update counts
        clutch.sc_thr_count -= 1
        cbg.thr_count_dec(timestamp)
        self.clutch_root.scr_thr_count -= 1
        cb.scb_thr_count -= 1

        # Handle clutch bucket becoming empty or updating
        if cb.scb_thr_count == 0:
            self.clutch_root.clutch_bucket_empty(cb, timestamp, SCHED_CLUTCH_BUCKET_OPTIONS_SAMEPRI_RR)
        else:
            self.clutch_root.clutch_bucket_update(
                cb, timestamp, SCHED_CLUTCH_BUCKET_OPTIONS_SAMEPRI_RR
            )

    # ------------------------------------------------------------------
    # Thread selection (for a processor)
    # Ports sched_clutch_hierarchy_thread_highest() + RT check
    # ------------------------------------------------------------------
    def _rt_prev_thread_can_continue(
        self, processor: Processor, prev_thread: Thread
    ) -> bool:
        """Model XNU's first-timeslice keep-running check for RT current thread."""
        if self.rt_runq.empty():
            return True

        # XNU only allows this keep-running fast path on first timeslice.
        if not processor.first_timeslice:
            return False

        rt_highest_pri = self.rt_runq.highest_priority()
        if rt_highest_pri < BASEPRI_RTQUEUES:
            return True

        if rt_highest_pri > prev_thread.sched_pri:
            if self.rt_runq.strict_priority:
                return False
            hi_thread = self.rt_runq.peek_highest_priority()
            if hi_thread is None:
                return True
            # sched_prim.c:2533 constraint safety check.
            if (
                prev_thread.rt_computation
                + hi_thread.rt_computation
                + self.rt_runq.deadline_epsilon
                >= hi_thread.rt_constraint
            ):
                return False
            return True

        # sched_prim.c:2537 earliest-deadline test.
        return (
            self.rt_runq.peek_deadline() + self.rt_runq.deadline_epsilon
            >= prev_thread.rt_deadline
        )

    def thread_select(
        self,
        processor: Processor,
        timestamp: int,
        prev_thread: Thread | None = None,
    ) -> tuple[Thread | None, bool]:
        """Select the highest-priority thread to run on this processor.

        When prev_thread is provided, it participates in selection even though
        it hasn't been re-enqueued yet (matching XNU's select-then-dispatch flow).

        Ports the thread selection logic from sched_prim.c:thread_select() and
        sched_clutch.c:sched_clutch_processor_highest_thread().

        Priority order:
        1. RT prev_thread keep-running check (first-timeslice rules)
        2. RT threads from queue
        3. Unbound Clutch hierarchy vs processor-bound runqueue (XNU tie rules)
        4. prev_thread as fallback (if runnable, per XNU line 3351-3354)
        5. None (processor goes idle)

        Returns (thread, chose_prev) where chose_prev=True means prev_thread
        was selected and should keep running without re-enqueue.
        """
        # Check RT queue first
        rt_thread = self.rt_runq.peek()

        # XNU line 2509-2580: current RT thread can continue on first timeslice
        # unless a better RT candidate exists.
        if prev_thread is not None and prev_thread.is_realtime:
            if self._rt_prev_thread_can_continue(processor, prev_thread):
                self._trace(
                    timestamp,
                    f"Select prev RT: {prev_thread.name} (deadline={prev_thread.rt_deadline})",
                )
                return prev_thread, True

            if rt_thread is not None:
                self._trace(
                    timestamp,
                    f"Select RT: {rt_thread.name} (deadline={rt_thread.rt_deadline})",
                )
                return self.rt_runq.dequeue(), False

            self._trace(
                timestamp,
                f"Select prev RT (fallback): {prev_thread.name} (deadline={prev_thread.rt_deadline})",
            )
            return prev_thread, True

        # Any enqueued RT thread beats non-RT candidates.
        if rt_thread is not None:
            self._trace(
                timestamp,
                f"Select RT: {rt_thread.name} (deadline={rt_thread.rt_deadline})",
            )
            return self.rt_runq.dequeue(), False

        bound_runq = self._bound_runq(processor)
        bound_thread = bound_runq.peek_max()
        bound_pri = bound_thread.sched_pri if bound_thread is not None else NOPRI
        clutch_pri = self.clutch_root.scr_priority

        prev_is_bound = (
            prev_thread is not None and prev_thread.bound_processor is processor
        )
        if prev_thread is not None:
            if prev_is_bound:
                bound_pri = max(bound_pri, prev_thread.sched_pri)
            else:
                clutch_pri = max(clutch_pri, prev_thread.sched_pri)

        # Compare non-RT sources: Clutch hierarchy vs processor-bound queue.
        # XNU line 3373-3384: ties prefer bound queue side.
        if clutch_pri > bound_pri:
            if self.clutch_root.scr_thr_count == 0:
                if prev_thread is not None:
                    self._trace(
                        timestamp,
                        f"Select prev (clutch-pri): {prev_thread.name} (pri={prev_thread.sched_pri})",
                    )
                    return prev_thread, True
                return None, False

            # Processor-bound threads don't participate in Clutch hierarchy lookup.
            prev_for_clutch = (
                prev_thread
                if (prev_thread is not None and prev_thread.bound_processor is None)
                else None
            )
            clutch_thread, _, chose_prev = self.clutch_root.hierarchy_thread_highest(
                timestamp, prev_for_clutch, processor.first_timeslice
            )
            if clutch_thread is not None:
                if chose_prev:
                    self._trace(
                        timestamp,
                        f"Select prev: {clutch_thread.name} (pri={clutch_thread.sched_pri})",
                    )
                    return clutch_thread, True
                self._trace(
                    timestamp,
                    f"Select TS: {clutch_thread.name} (pri={clutch_thread.sched_pri})",
                )
                self.thread_remove(clutch_thread, timestamp)
                return clutch_thread, False
        else:
            if len(bound_runq) == 0 or (
                prev_is_bound
                and self._pri_greater_tiebreak(
                    prev_thread.sched_pri,
                    bound_pri,
                    processor.first_timeslice,
                )
            ):
                if prev_thread is None:
                    return None, False
                self._trace(
                    timestamp,
                    f"Select prev bound: {prev_thread.name} (pri={prev_thread.sched_pri})",
                )
                return prev_thread, True

            if bound_thread is not None:
                selected = bound_runq.pop_max()
                self._trace(
                    timestamp,
                    f"Select bound: {selected.name} (pri={selected.sched_pri})",
                )
                return selected, False

        # XNU line 3351-3354: If runqueue is empty, prev_thread keeps running
        if prev_thread is not None:
            self._trace(
                timestamp,
                f"Select prev (fallback): {prev_thread.name} (pri={prev_thread.sched_pri})",
            )
            return prev_thread, True

        return None, False

    # ------------------------------------------------------------------
    # Context switch / dispatch
    # ------------------------------------------------------------------
    def thread_dispatch(
        self,
        processor: Processor,
        old_thread: Thread | None,
        new_thread: Thread,
        timestamp: int,
        reason: str = "scheduler dispatch",
    ) -> None:
        """Perform a context switch on a processor.

        Handles CPU accounting for old thread, quantum setup for new thread.
        """
        if old_thread is not None and old_thread is not new_thread:
            # Account CPU time for old thread
            if old_thread.computation_epoch > 0:
                cpu_time = timestamp - old_thread.computation_epoch
                old_thread.total_cpu_us += cpu_time
                old_thread.computation_epoch = 0

                # Update timeshare decay for old thread
                if old_thread.thread_group.sched_clutch is not None:
                    cbg = old_thread.thread_group.sched_clutch.sc_clutch_groups[
                        old_thread.th_sched_bucket
                    ]
                    update_thread_cpu_usage(old_thread, cpu_time, cbg)

            # Update blocked time tracking
            if old_thread.state == ThreadState.WAITING:
                # Thread is blocking: update its wait start time
                old_thread.last_run_time = timestamp
            elif old_thread.state == ThreadState.RUNNABLE:
                # Thread was preempted: re-enqueue
                old_thread.preemption_count += 1

            old_thread.context_switches += 1
            processor.context_switches += 1

        # Set up new thread on processor
        new_thread.state = ThreadState.RUNNING
        new_thread.computation_epoch = timestamp
        new_thread.last_run_time = timestamp

        # Calculate scheduling latency
        if new_thread.last_made_runnable_time > 0:
            latency = timestamp - new_thread.last_made_runnable_time
            new_thread.total_wait_us += latency

        # Set quantum
        if new_thread.quantum_remaining <= 0:
            new_thread.reset_quantum()

        processor.active_thread = new_thread
        processor.current_pri = new_thread.sched_pri
        processor.state = ProcessorState.RUNNING
        processor.first_timeslice = new_thread.first_timeslice
        processor.starting_pri = new_thread.sched_pri
        processor.last_dispatch_time = timestamp

        new_thread.context_switches += 1
        self._log_processor_switch(timestamp, processor, old_thread, new_thread, reason)

        self._trace(
            timestamp,
            f"Dispatch: CPU{processor.processor_id} <- {new_thread.name} "
            f"(pri={new_thread.sched_pri}, quantum={new_thread.quantum_remaining}us)",
        )

    # ------------------------------------------------------------------
    # Quantum expiry
    # ------------------------------------------------------------------
    def thread_quantum_expire(
        self, processor: Processor, timestamp: int
    ) -> Thread | None:
        """Handle quantum expiry for the current thread on a processor.

        Matches XNU's select-then-dispatch flow: the old thread is NOT
        re-enqueued before selection. Instead it participates in EDF as
        prev_thread, and is only re-enqueued afterward if a different
        thread was selected.
        """
        old_thread = processor.active_thread
        if old_thread is None:
            return None

        # Account CPU time
        if old_thread.computation_epoch > 0:
            cpu_time = timestamp - old_thread.computation_epoch
            old_thread.total_cpu_us += cpu_time
            old_thread.computation_epoch = 0

            if old_thread.thread_group.sched_clutch is not None:
                cbg = old_thread.thread_group.sched_clutch.sc_clutch_groups[
                    old_thread.th_sched_bucket
                ]
                update_thread_cpu_usage(old_thread, cpu_time, cbg)

        # Match XNU thread_quantum_expire() priority refresh semantics:
        # if sched_tick advanced, age/update even when the same thread continues.
        if old_thread.is_timeshare:
            self._timeshare_setrun_update(old_thread)

        old_thread.first_timeslice = False
        old_thread.quantum_remaining = 0
        if old_thread.is_realtime:
            # sched_prim.c: consumed RT quantum marks deadline as expired.
            old_thread.rt_deadline = RT_DEADLINE_QUANTUM_EXPIRED
        old_thread.state = ThreadState.RUNNABLE

        self._trace(
            timestamp,
            f"Quantum expire: {old_thread.name} on CPU{processor.processor_id} "
            f"(new sched_pri={old_thread.sched_pri})",
        )

        # Select next thread WITH old_thread as prev_thread (not yet enqueued)
        new_thread, chose_prev = self.thread_select(
            processor, timestamp, prev_thread=old_thread
        )

        if chose_prev and new_thread is old_thread:
            # Old thread won EDF — keep running it, no re-enqueue needed
            self.thread_dispatch(
                processor,
                old_thread,
                old_thread,
                timestamp,
                reason=(
                    f"quantum expired for {old_thread.name}, but it remained best eligible thread"
                ),
            )
            return old_thread

        if new_thread is not None:
            # Different thread selected — now re-enqueue old thread at tail
            self.thread_setrun(old_thread, timestamp, options=SCHED_TAILQ)
            self.thread_dispatch(
                processor,
                old_thread,
                new_thread,
                timestamp,
                reason=(
                    f"quantum expired for {old_thread.name}; switched to higher-ranked runnable thread"
                ),
            )
            return new_thread

        # No better thread found. Keep running old thread without runqueue re-insert.
        self.thread_dispatch(
            processor,
            old_thread,
            old_thread,
            timestamp,
            reason=f"quantum expired for {old_thread.name}; no better runnable thread",
        )
        return old_thread

    # ------------------------------------------------------------------
    # Thread blocking
    # ------------------------------------------------------------------
    def thread_block(self, thread: Thread, processor: Processor, timestamp: int) -> Thread | None:
        """Handle a thread voluntarily blocking (sleeping/waiting).

        Returns the new thread dispatched on the processor, or None if idle.
        """
        # Account CPU time
        if thread.computation_epoch > 0:
            cpu_time = timestamp - thread.computation_epoch
            thread.total_cpu_us += cpu_time
            thread.computation_epoch = 0

            if thread.thread_group.sched_clutch is not None:
                cbg = thread.thread_group.sched_clutch.sc_clutch_groups[
                    thread.th_sched_bucket
                ]
                update_thread_cpu_usage(thread, cpu_time, cbg)

        # XNU clears old quantum state when a waiting thread is unblocked
        # (thread_unblock -> thread->quantum_remaining = 0). Model that by
        # dropping any remainder at block time in this simulator.
        thread.quantum_remaining = 0

        thread.state = ThreadState.WAITING
        thread.last_run_time = timestamp

        # XNU decrements run_count when a thread leaves runnable/running state.
        if (not thread.is_realtime) and thread.bound_processor is None:
            clutch = thread.thread_group.sched_clutch
            if clutch is not None:
                cbg = clutch.sc_clutch_groups[thread.th_sched_bucket]
                cbg.run_count_dec(timestamp)

        self._trace(
            timestamp,
            f"Block: {thread.name} on CPU{processor.processor_id}",
        )

        # Select next thread (no prev_thread: blocking thread can't keep running)
        new_thread, _ = self.thread_select(processor, timestamp)
        if new_thread is not None:
            self.thread_dispatch(
                processor,
                thread,
                new_thread,
                timestamp,
                reason=(
                    f"{thread.name} blocked (voluntary sleep/I/O); selected next runnable thread"
                ),
            )
            return new_thread

        # Processor goes idle
        self._log_processor_switch(
            timestamp,
            processor,
            thread,
            None,
            reason=f"{thread.name} blocked and no runnable replacement was available",
        )
        processor.active_thread = None
        processor.current_pri = NOPRI
        processor.state = ProcessorState.IDLE
        return None

    # ------------------------------------------------------------------
    # Thread wakeup (unblock)
    # ------------------------------------------------------------------
    def thread_wakeup(self, thread: Thread, timestamp: int) -> Processor | None:
        """Wake up a blocked thread, making it runnable.

        Returns a processor to signal for preemption if needed.
        """
        if thread.state != ThreadState.WAITING:
            return None

        # Update the thread's wait time stats
        if thread.last_run_time > 0:
            wait_time = timestamp - thread.last_run_time
            # cpu_blocked is tracked in the bucket group via run_count_inc

        if thread.is_realtime:
            # thread_unblock() assigns a fresh deadline on wakeup.
            thread.rt_deadline = timestamp + thread.rt_constraint

        self._trace(timestamp, f"Wakeup: {thread.name}")
        # XNU thread_go() enqueues wakeups with SCHED_PREEMPT | SCHED_TAILQ.
        return self.thread_setrun(
            thread, timestamp, options=(SCHED_PREEMPT | SCHED_TAILQ)
        )

    # ------------------------------------------------------------------
    # Periodic maintenance (sched_tick)
    # ------------------------------------------------------------------
    def sched_tick(self, timestamp: int) -> None:
        """Periodic scheduler maintenance, called every SCHED_TICK_INTERVAL.

        Updates load calculations, ages CPU data for all runnable clutch bucket groups.
        """
        self.current_tick += 1

        # Update pri_shift for all runnable clutch bucket groups
        for cb in self.clutch_root.scr_clutch_buckets_list:
            cbg = cb.scb_group
            cbg.pri_shift_update(self.current_tick, self.pset.processor_count)

        # Age CPU usage for all runnable threads
        for cb in self.clutch_root.scr_clutch_buckets_list:
            cbg = cb.scb_group
            reprioritized = False
            for thread in cb.scb_timeshare_threads:
                if thread.is_timeshare:
                    age_thread_cpu_usage(thread)
                    thread.sched_stamp = self.current_tick
                    # Match XNU update_priority(): apply the current bucket-group
                    # shift after aging, then compute sched_pri from sched_usage.
                    thread.pri_shift = cbg.scbg_pri_shift
                    new_pri = compute_sched_pri(thread, cbg)
                    if new_pri != thread.sched_pri:
                        thread.sched_pri = new_pri
                        reprioritized = True
            if reprioritized:
                # Keep bucket runqueue ordering consistent with updated sched_pri.
                cb.scb_thread_runq.refresh_priorities()
            # Match XNU sched_clutch_bucket_group_timeshare_update():
            # refresh clutch bucket priority/interactivity in hierarchy each tick.
            if cb.scb_root is not None:
                self.clutch_root.clutch_bucket_update(
                    cb, timestamp, SCHED_CLUTCH_BUCKET_OPTIONS_NONE
                )

        self._trace(
            timestamp,
            f"Sched tick #{self.current_tick}: "
            f"{self.clutch_root.scr_thr_count} runnable threads",
        )

    # ------------------------------------------------------------------
    # Preemption check
    # ------------------------------------------------------------------
    def _check_preemption(
        self, new_thread: Thread, timestamp: int, options: int = SCHED_PREEMPT
    ) -> Processor | None:
        """Check if a newly enqueued thread should preempt a running thread.

        Returns the processor that should be preempted, or None.
        """
        explicit_preempt = bool(options & SCHED_PREEMPT)
        preempt_allowed = explicit_preempt or (
            new_thread.sched_pri >= BASEPRI_PREEMPT
        )

        # Bound threads can only preempt their target processor.
        if new_thread.bound_processor is not None:
            target = new_thread.bound_processor
            active = target.active_thread
            if active is None:
                self._set_preemption_reason(
                    target,
                    f"{new_thread.name} became runnable and CPU{target.processor_id} was idle",
                )
                return target
            if new_thread.is_realtime:
                if not active.is_realtime:
                    self._set_preemption_reason(
                        target,
                        (
                            f"RT thread {new_thread.name} preempted non-RT "
                            f"{active.name}"
                        ),
                    )
                    return target
                if new_thread.sched_pri > active.sched_pri:
                    # Match realtime_setrun(): higher-priority RT requests preemption.
                    # Constraint/first-timeslice keep-running behavior is enforced
                    # in thread_select(), but preemption request itself follows
                    # realtime_setrun() priority/deadline conditions.
                    self._set_preemption_reason(
                        target,
                        (
                            f"RT thread {new_thread.name} has higher RT priority "
                            f"than {active.name}"
                        ),
                    )
                    return target
                if (
                    new_thread.sched_pri == active.sched_pri
                    and new_thread.rt_deadline + self.rt_runq.deadline_epsilon < active.rt_deadline
                ):
                    self._set_preemption_reason(
                        target,
                        (
                            f"RT thread {new_thread.name} has earlier deadline "
                            f"than {active.name}"
                        ),
                    )
                    return target
                return None
            if preempt_allowed:
                if new_thread.sched_pri > active.sched_pri:
                    self._set_preemption_reason(
                        target,
                        (
                            f"{new_thread.name} has higher priority "
                            f"than running {active.name}"
                        ),
                    )
                    return target
                if (
                    new_thread.sched_pri == active.sched_pri
                    and explicit_preempt
                ):
                    self._set_preemption_reason(
                        target,
                        (
                            f"{new_thread.name} requested explicit preemption "
                            f"against equal-priority {active.name}"
                        ),
                    )
                    return target
            return None

        # Try to find an idle processor first
        idle_proc = self.pset.find_idle_processor()
        if idle_proc is not None:
            self._set_preemption_reason(
                idle_proc,
                f"{new_thread.name} became runnable and was placed on an idle processor",
            )
            return idle_proc

        # RT threads preempt non-RT, and may preempt peer RT threads if
        # priority/deadline indicate the new thread is better.
        if new_thread.is_realtime:
            for proc in self.pset.processors:
                active = proc.active_thread
                if active is None:
                    self._set_preemption_reason(
                        proc,
                        f"RT thread {new_thread.name} found an idle processor",
                    )
                    return proc
                if not active.is_realtime:
                    self._set_preemption_reason(
                        proc,
                        (
                            f"RT thread {new_thread.name} preempted non-RT "
                            f"{active.name}"
                        ),
                    )
                    return proc
                if new_thread.sched_pri > active.sched_pri:
                    # Match realtime_setrun(): higher-priority RT requests preemption.
                    # thread_select() applies current-thread keep-running rules.
                    self._set_preemption_reason(
                        proc,
                        (
                            f"RT thread {new_thread.name} has higher RT priority "
                            f"than {active.name}"
                        ),
                    )
                    return proc
                if (
                    new_thread.sched_pri == active.sched_pri
                    and new_thread.rt_deadline + self.rt_runq.deadline_epsilon < active.rt_deadline
                ):
                    self._set_preemption_reason(
                        proc,
                        (
                            f"RT thread {new_thread.name} has earlier deadline "
                            f"than {active.name}"
                        ),
                    )
                    return proc
            return None

        # Find the lowest-priority running thread
        lowest_proc = self.pset.find_lowest_priority_processor()
        if (
            preempt_allowed
            and lowest_proc is not None
            and new_thread.sched_pri > lowest_proc.current_pri
        ):
            active = lowest_proc.active_thread
            target_name = active.name if active is not None else "idle"
            self._set_preemption_reason(
                lowest_proc,
                (
                    f"{new_thread.name} outranked lowest-priority running thread "
                    f"{target_name}"
                ),
            )
            return lowest_proc

        if preempt_allowed:
            # XNU can preempt on equal priority once the running thread is
            # past first_timeslice (tiebreak no longer favors current thread).
            for proc in self.pset.processors:
                active = proc.active_thread
                if (
                    active is not None
                    and (not active.is_realtime)
                    and proc.current_pri == new_thread.sched_pri
                    and explicit_preempt
                ):
                    self._set_preemption_reason(
                        proc,
                        (
                            f"{new_thread.name} requested explicit preemption "
                            f"against equal-priority {active.name}"
                        ),
                    )
                    return proc

        return None

    # ------------------------------------------------------------------
    # Urgency tracking
    # ------------------------------------------------------------------
    def urgency_inc(self, thread: Thread) -> None:
        if is_above_timeshare(thread.th_sched_bucket) or thread.is_realtime:
            self.clutch_root.scr_urgency += 1

    def urgency_dec(self, thread: Thread) -> None:
        if is_above_timeshare(thread.th_sched_bucket) or thread.is_realtime:
            self.clutch_root.scr_urgency = max(0, self.clutch_root.scr_urgency - 1)
