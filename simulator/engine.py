"""
Discrete-event simulation engine for the XNU Clutch Scheduler.

Drives the simulation by processing events in timestamp order,
calling into the Scheduler for thread management decisions.
"""

from __future__ import annotations

import heapq
from typing import TYPE_CHECKING

from xnu_sched.constants import (
    SCHED_TICK_INTERVAL_US,
    SCHED_HEADQ,
    SCHED_TAILQ,
    SCHED_PREEMPT,
    RT_DEADLINE_QUANTUM_EXPIRED,
)
from xnu_sched.thread import Thread, ThreadState
from xnu_sched.processor import Processor, ProcessorSet, ProcessorState
from xnu_sched.scheduler import Scheduler

from .events import Event, EventType, EVENT_PRIORITY
from .workload import BehaviorProfile
from .stats import StatsCollector

if TYPE_CHECKING:
    pass


class SimulationEngine:
    """Discrete-event simulation engine.

    Processes events in chronological order, driving the Clutch scheduler
    to make scheduling decisions. Tracks statistics for reporting.
    """

    __slots__ = (
        "clock",
        "event_queue",
        "event_seq",
        "scheduler",
        "pset",
        "stats",
        "thread_behaviors",
        "_thread_block_deadlines",
        "trace",
    )

    def __init__(
        self,
        num_cpus: int = 4,
        trace: bool = False,
    ) -> None:
        self.clock: int = 0
        self.event_queue: list[Event] = []
        self.event_seq: int = 0

        self.pset = ProcessorSet(pset_id=0, num_cpus=num_cpus)
        self.scheduler = Scheduler(self.pset, trace=trace)
        self.stats = StatsCollector(num_cpus)
        self.trace = trace

        # Maps thread_id -> BehaviorProfile for event generation
        self.thread_behaviors: dict[int, BehaviorProfile] = {}
        # Tracks the latest scheduled voluntary block event per thread.
        self._thread_block_deadlines: dict[int, int] = {}

    def schedule_event(self, event: Event) -> None:
        """Add an event to the event queue."""
        event.priority = EVENT_PRIORITY.get(event.event_type, 50)
        event._seq = self.event_seq
        self.event_seq += 1
        heapq.heappush(self.event_queue, event)

    def add_thread(self, thread: Thread, behavior: BehaviorProfile, start_time: int = 0) -> None:
        """Register a thread with the engine and schedule its initial wakeup."""
        self.scheduler.all_threads.append(thread)
        self.thread_behaviors[thread.tid] = behavior
        self.stats.register_thread(thread)

        if thread.is_realtime:
            # RT threads: schedule first period start
            self.schedule_event(Event(
                timestamp=start_time,
                event_type=EventType.RT_PERIOD_START,
                thread_id=thread.tid,
            ))
        else:
            # Timeshare threads: schedule initial wakeup
            self.schedule_event(Event(
                timestamp=start_time,
                event_type=EventType.THREAD_WAKEUP,
                thread_id=thread.tid,
            ))

    def run(self, duration_us: int) -> None:
        """Run the simulation for the specified duration."""
        # Schedule end event
        self.schedule_event(Event(
            timestamp=duration_us,
            event_type=EventType.SIMULATION_END,
        ))

        # Schedule periodic sched_tick events
        tick_time = SCHED_TICK_INTERVAL_US
        while tick_time < duration_us:
            self.schedule_event(Event(
                timestamp=tick_time,
                event_type=EventType.SCHED_TICK,
            ))
            tick_time += SCHED_TICK_INTERVAL_US

        # Main event loop
        while self.event_queue:
            event = heapq.heappop(self.event_queue)
            if event.timestamp > duration_us:
                break
            if event.event_type == EventType.SIMULATION_END:
                self.clock = event.timestamp
                break

            self.clock = event.timestamp
            self._handle_event(event)

        # Finalize: account for threads still running
        for proc in self.pset.processors:
            if proc.active_thread is not None:
                thread = proc.active_thread
                if thread.computation_epoch > 0:
                    cpu_time = self.clock - thread.computation_epoch
                    thread.total_cpu_us += cpu_time
                    thread.computation_epoch = 0

        self.stats.finalize(self.scheduler.all_threads, self.clock)

    def _handle_event(self, event: Event) -> None:
        """Dispatch an event to the appropriate handler."""
        handler = self._handlers.get(event.event_type)
        if handler:
            handler(self, event)

    def _handle_thread_wakeup(self, event: Event) -> None:
        """Handle a thread becoming runnable."""
        thread = self._find_thread(event.thread_id)
        if thread is None or thread.state == ThreadState.TERMINATED:
            return

        self.stats.wakeup_count += 1

        preempt_proc = self.scheduler.thread_wakeup(thread, self.clock)

        if preempt_proc is not None:
            self._handle_preemption(preempt_proc)

    def _handle_thread_block(self, event: Event) -> None:
        """Handle a thread voluntarily blocking."""
        thread = self._find_thread(event.thread_id)
        if thread is None:
            return

        expected_block = self._thread_block_deadlines.get(thread.tid)
        if expected_block is not None and event.timestamp != expected_block:
            # Ignore stale block events from a previous dispatch slice.
            return
        if thread.state != ThreadState.RUNNING:
            # Block timer fired while thread was off-core; discard this armed deadline.
            if expected_block is not None and event.timestamp == expected_block:
                self._thread_block_deadlines.pop(thread.tid, None)
            return

        self.stats.block_count += 1

        # Find which processor this thread is on
        proc = self._find_processor_for_thread(thread)
        if proc is None:
            return

        self._thread_block_deadlines.pop(thread.tid, None)

        # Block the thread
        new_thread = self.scheduler.thread_block(thread, proc, self.clock)

        # Record dispatch if a new thread was selected
        if new_thread is not None:
            self.stats.record_dispatch(new_thread, self.clock)
            self.stats.record_context_switch()
            self._schedule_quantum_expire(proc, new_thread)
            if not new_thread.is_realtime:
                self._schedule_thread_block(new_thread)
        else:
            # Processor went idle: try to find work
            self._try_dispatch_idle(
                proc,
                reason=(
                    f"{thread.name} blocked and CPU{proc.processor_id} became idle; "
                    "attempting to dispatch any newly runnable work"
                ),
            )

        # Schedule the thread's next wakeup
        behavior = self.thread_behaviors.get(thread.tid)
        if behavior and not thread.is_realtime:
            block_duration = behavior.sample_block_duration()
            self.schedule_event(Event(
                timestamp=self.clock + block_duration,
                event_type=EventType.THREAD_WAKEUP,
                thread_id=thread.tid,
            ))

    def _handle_quantum_expire(self, event: Event) -> None:
        """Handle quantum expiry for a processor."""
        proc = self.pset.processors[event.processor_id]
        if proc.active_thread is None:
            return

        # Verify this quantum event is still current
        if proc.active_thread.tid != event.thread_id:
            return
        if event.timestamp != proc.quantum_end:
            return

        self.stats.quantum_expire_count += 1

        old_thread = proc.active_thread
        new_thread = self.scheduler.thread_quantum_expire(proc, self.clock)

        if new_thread is not None and new_thread is not old_thread:
            self.stats.record_dispatch(new_thread, self.clock)
            self.stats.record_context_switch()
            self._schedule_quantum_expire(proc, new_thread)
            # Schedule old thread's next block event
            self._schedule_thread_block(old_thread)
        elif proc.active_thread is not None:
            # Same or old thread continues
            self._schedule_quantum_expire(proc, proc.active_thread)

    def _handle_sched_tick(self, event: Event) -> None:
        """Handle periodic scheduler maintenance."""
        self.stats.tick_count += 1
        self.scheduler.sched_tick(self.clock)

    def _handle_rt_period_start(self, event: Event) -> None:
        """Handle an RT thread's periodic activation."""
        thread = self._find_thread(event.thread_id)
        if thread is None or thread.state == ThreadState.TERMINATED:
            return

        behavior = self.thread_behaviors.get(thread.tid)
        if behavior is None:
            return

        # Set deadline for this period
        thread.rt_deadline = self.clock + behavior.rt_constraint_us

        if thread.state == ThreadState.WAITING:
            # Wake up the thread
            self.stats.wakeup_count += 1
            preempt_proc = self.scheduler.thread_setrun(
                thread, self.clock, options=(SCHED_PREEMPT | SCHED_TAILQ)
            )
            if preempt_proc is not None:
                self._handle_preemption(preempt_proc)

        # Schedule the block after computation
        self.schedule_event(Event(
            timestamp=self.clock + behavior.rt_computation_us,
            event_type=EventType.THREAD_BLOCK,
            thread_id=thread.tid,
        ))

        # Schedule next period
        if behavior.rt_period_us > 0:
            self.schedule_event(Event(
                timestamp=self.clock + behavior.rt_period_us,
                event_type=EventType.RT_PERIOD_START,
                thread_id=thread.tid,
            ))

    def _handle_preemption(self, proc: Processor) -> None:
        """Handle preemption on a processor.

        Matches XNU's select-then-dispatch flow: old thread is NOT re-enqueued
        before selection. It participates as prev_thread in EDF, and is only
        re-enqueued afterward if a different thread was selected.
        """
        preemption_reason = self.scheduler.consume_preemption_reason(proc)
        if proc.is_idle:
            # Idle processor: just dispatch
            self._try_dispatch_idle(
                proc,
                reason=f"preemption signal on idle CPU: {preemption_reason}",
            )
            return

        old_thread = proc.active_thread
        if old_thread is None:
            self._try_dispatch_idle(
                proc,
                reason=f"preemption signal with no active thread: {preemption_reason}",
            )
            return

        # Account CPU time for preempted thread
        if old_thread.computation_epoch > 0:
            cpu_time = self.clock - old_thread.computation_epoch
            old_thread.total_cpu_us += cpu_time
            old_thread.computation_epoch = 0

            if old_thread.thread_group.sched_clutch is not None:
                from xnu_sched.timeshare import update_thread_cpu_usage
                cbg = old_thread.thread_group.sched_clutch.sc_clutch_groups[
                    old_thread.th_sched_bucket
                ]
                update_thread_cpu_usage(old_thread, cpu_time, cbg)

        # Match XNU keep_quantum rules when switching out a runnable thread.
        keep_quantum = (
            proc.first_timeslice and proc.starting_pri <= old_thread.sched_pri
        )
        if keep_quantum:
            old_thread.quantum_remaining = max(
                0, old_thread.quantum_remaining - (self.clock - proc.last_dispatch_time)
            )
        else:
            old_thread.quantum_remaining = 0
        if old_thread.is_realtime and old_thread.quantum_remaining == 0:
            old_thread.rt_deadline = RT_DEADLINE_QUANTUM_EXPIRED
        old_thread.state = ThreadState.RUNNABLE
        # Match XNU thread_select(): current-thread update_priority() runs before
        # selection whenever sched_tick has advanced.
        if old_thread.is_timeshare:
            self.scheduler._timeshare_setrun_update(old_thread)
        self.stats.record_preemption()

        # Select new thread WITH old_thread as prev_thread (not yet enqueued)
        new_thread, chose_prev = self.scheduler.thread_select(
            proc, self.clock, prev_thread=old_thread
        )

        if chose_prev and new_thread is old_thread:
            # Old thread won selection — keep running, no re-enqueue
            self.scheduler.thread_dispatch(
                proc,
                old_thread,
                old_thread,
                self.clock,
                reason=(
                    f"preemption requested ({preemption_reason}), but "
                    f"{old_thread.name} remained best eligible thread"
                ),
            )
            self._schedule_quantum_expire(proc, old_thread)
            return

        if new_thread is not None:
            # Different thread selected — now re-enqueue old thread at head
            self.scheduler.thread_setrun(old_thread, self.clock, options=SCHED_HEADQ)
            self.scheduler.thread_dispatch(
                proc,
                old_thread,
                new_thread,
                self.clock,
                reason=f"preemption: {preemption_reason}",
            )
            self.stats.record_dispatch(new_thread, self.clock)
            self.stats.record_context_switch()
            self._schedule_quantum_expire(proc, new_thread)
            # Schedule block for new thread if it's a timeshare thread
            if not new_thread.is_realtime:
                self._schedule_thread_block(new_thread)
        else:
            # Nothing better runnable — keep old thread running in place.
            self.scheduler.thread_dispatch(
                proc,
                old_thread,
                old_thread,
                self.clock,
                reason=(
                    f"preemption requested ({preemption_reason}), but no "
                    "better runnable replacement was selected"
                ),
            )
            self._schedule_quantum_expire(proc, old_thread)

    def _try_dispatch_idle(
        self,
        proc: Processor,
        reason: str = "dispatching work to idle CPU",
    ) -> None:
        """Try to dispatch a thread on an idle processor."""
        new_thread, _ = self.scheduler.thread_select(proc, self.clock)
        if new_thread is not None:
            self.scheduler.thread_dispatch(
                proc,
                None,
                new_thread,
                self.clock,
                reason=reason,
            )
            self.stats.record_dispatch(new_thread, self.clock)
            self._schedule_quantum_expire(proc, new_thread)
            if not new_thread.is_realtime:
                self._schedule_thread_block(new_thread)

    def _schedule_quantum_expire(self, proc: Processor, thread: Thread) -> None:
        """Schedule quantum expiry event for a thread on a processor."""
        quantum = thread.quantum_remaining
        if quantum <= 0:
            thread.reset_quantum()
            quantum = thread.quantum_remaining

        expire_time = self.clock + quantum
        proc.quantum_end = expire_time

        self.schedule_event(Event(
            timestamp=expire_time,
            event_type=EventType.QUANTUM_EXPIRE,
            thread_id=thread.tid,
            processor_id=proc.processor_id,
        ))

    def _schedule_thread_block(self, thread: Thread) -> None:
        """Schedule a voluntary block event for a timeshare thread."""
        behavior = self.thread_behaviors.get(thread.tid)
        if behavior is None or thread.is_realtime:
            return

        burst = behavior.sample_cpu_burst()
        # Thread will block after using some CPU
        block_time = self.clock + burst
        self._thread_block_deadlines[thread.tid] = block_time
        self.schedule_event(Event(
            timestamp=block_time,
            event_type=EventType.THREAD_BLOCK,
            thread_id=thread.tid,
        ))

    def _find_thread(self, tid: int) -> Thread | None:
        for t in self.scheduler.all_threads:
            if t.tid == tid:
                return t
        return None

    def _find_processor_for_thread(self, thread: Thread) -> Processor | None:
        for proc in self.pset.processors:
            if proc.active_thread is thread:
                return proc
        return None

    # Event handler dispatch table
    _handlers = {
        EventType.THREAD_WAKEUP: _handle_thread_wakeup,
        EventType.THREAD_BLOCK: _handle_thread_block,
        EventType.QUANTUM_EXPIRE: _handle_quantum_expire,
        EventType.SCHED_TICK: _handle_sched_tick,
        EventType.RT_PERIOD_START: _handle_rt_period_start,
    }
