"""Application runtime orchestrating human tasks on top of xnu_sched."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock, Timer
from typing import Callable

from xnu_sched.clutch import SchedClutch
from xnu_sched.constants import (
    RT_DEADLINE_QUANTUM_EXPIRED,
    SCHED_HEADQ,
    SCHED_PREEMPT,
    SCHED_TAILQ,
    SCHED_TICK_INTERVAL_US,
)
from xnu_sched.processor import Processor, ProcessorSet
from xnu_sched.scheduler import Scheduler
from xnu_sched.thread import Thread, ThreadGroup, ThreadState
from xnu_sched.timeshare import update_thread_cpu_usage

from human_sched.adapters.terminal_notifier import TerminalNotifier
from human_sched.adapters.time_scale import (
    TimeScaleAdapter,
    load_time_scale_config,
)
from human_sched.domain.life_area import LifeArea
from human_sched.domain.task import Task
from human_sched.domain.urgency import UrgencyTier
from human_sched.ports.notifications import NotificationEventType, NotificationPort


@dataclass(slots=True)
class Dispatch:
    """Result of an atomic 'what next?' select+dispatch operation."""

    task: Task
    life_area: LifeArea
    urgency_tier: UrgencyTier
    focus_block_hours: float
    reason: str


class HumanTaskScheduler:
    """Single-CPU human task scheduler powered by the XNU Clutch engine."""

    __slots__ = (
        "scheduler",
        "pset",
        "processor",
        "notifier",
        "time_scale",
        "max_catchup_ticks",
        "life_areas_by_id",
        "_life_areas_by_name",
        "tasks_by_id",
        "_lock",
        "_enable_timers",
        "_quantum_timer",
        "_tick_timer",
        "_quantum_notification_id",
        "_tick_notification_id",
        "_last_tick_us",
    )

    def __init__(
        self,
        *,
        env_file: str = ".env",
        notifier: NotificationPort | None = None,
        time_scale: TimeScaleAdapter | None = None,
        enable_timers: bool = True,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        if time_scale is None:
            cfg = load_time_scale_config(env_file)
            time_scale = TimeScaleAdapter(config=cfg, now_provider=now_provider)

        self.time_scale = time_scale
        self.max_catchup_ticks = self.time_scale.config.max_catchup_ticks

        self.notifier: NotificationPort = notifier or TerminalNotifier()

        self.pset = ProcessorSet(pset_id=0, num_cpus=1)
        self.processor = self.pset.processors[0]
        self.scheduler = Scheduler(self.pset, trace=True)

        self.life_areas_by_id: dict[int, LifeArea] = {}
        self._life_areas_by_name: dict[str, LifeArea] = {}
        self.tasks_by_id: dict[int, Task] = {}

        self._lock = RLock()
        self._enable_timers = enable_timers
        self._quantum_timer: Timer | None = None
        self._tick_timer: Timer | None = None
        self._quantum_notification_id: str | None = None
        self._tick_notification_id: str | None = None
        self._last_tick_us = 0

        self._arm_tick_timer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Stop any background timers and pending notifications."""
        with self._lock:
            self._cancel_quantum_artifacts(reset_quantum_end=True)
            self._cancel_tick_artifacts()

    # ------------------------------------------------------------------
    # CRUD-style API
    # ------------------------------------------------------------------
    def create_life_area(self, name: str, description: str = "") -> LifeArea:
        with self._lock:
            key = self._normalize_name(name)
            if key in self._life_areas_by_name:
                return self._life_areas_by_name[key]

            tg = ThreadGroup(name)
            SchedClutch(tg, num_clusters=1)
            life_area = LifeArea(name=name, description=description, thread_group=tg)

            self.life_areas_by_id[life_area.life_area_id] = life_area
            self._life_areas_by_name[key] = life_area
            self.scheduler.all_thread_groups.append(tg)
            return life_area

    def create_task(
        self,
        life_area: LifeArea | int | str,
        title: str,
        *,
        urgency_tier: UrgencyTier | str = UrgencyTier.NORMAL,
        description: str = "",
        notes: str = "",
        due_at: datetime | None = None,
        start_runnable: bool = True,
    ) -> Task:
        with self._lock:
            now_us = self._now_us()
            self._apply_lazy_catchup(now_us)

            area = self._resolve_life_area(life_area)
            urgency = UrgencyTier.from_value(urgency_tier)

            thread = Thread(
                thread_group=area.thread_group,
                sched_mode=urgency.sched_mode,
                base_pri=urgency.base_priority,
                name=self._thread_name_from_title(title),
            )

            task = Task(
                title=title,
                life_area=area,
                urgency_tier=urgency,
                thread=thread,
                description=description,
                notes=notes,
                due_at=due_at,
            )

            self.tasks_by_id[task.task_id] = task
            area.task_ids.add(task.task_id)
            self.scheduler.all_threads.append(thread)

            if start_runnable:
                preempt_proc = self.scheduler.thread_setrun(
                    thread,
                    now_us,
                    options=(SCHED_PREEMPT | SCHED_TAILQ),
                )
                self._handle_preemption_request(
                    preempt_proc,
                    now_us,
                    trigger_when_idle=False,
                )

            return task

    def pause_task(self, task_id: int | None = None) -> Task | None:
        with self._lock:
            now_us = self._now_us()
            self._apply_lazy_catchup(now_us)

            task = self._resolve_task(task_id)
            if task is None:
                return None

            thread = task.thread
            if thread.state == ThreadState.TERMINATED:
                return task
            if thread.state == ThreadState.WAITING:
                return task

            if thread.state == ThreadState.RUNNABLE:
                self.scheduler.thread_remove(thread, now_us)
                thread.state = ThreadState.WAITING
                thread.last_run_time = now_us
                return task

            if thread.state == ThreadState.RUNNING:
                new_thread = self.scheduler.thread_block(thread, self.processor, now_us)
                if new_thread is not None:
                    self._arm_quantum_for_active(now_us)
                else:
                    self._cancel_quantum_artifacts(reset_quantum_end=True)
                return task

            return task

    def resume_task(self, task_id: int) -> Task:
        with self._lock:
            now_us = self._now_us()
            self._apply_lazy_catchup(now_us)

            task = self._require_task(task_id)
            thread = task.thread

            if thread.state == ThreadState.TERMINATED:
                raise ValueError(f"Task {task_id} is completed and cannot be resumed")

            if thread.state == ThreadState.WAITING:
                preempt_proc = self.scheduler.thread_wakeup(thread, now_us)
                self._handle_preemption_request(
                    preempt_proc,
                    now_us,
                    trigger_when_idle=False,
                )
            return task

    def complete_task(self, task_id: int | None = None) -> Task | None:
        with self._lock:
            now_us = self._now_us()
            self._apply_lazy_catchup(now_us)

            task = self._resolve_task(task_id)
            if task is None:
                return None

            thread = task.thread
            if thread.state == ThreadState.TERMINATED:
                return task

            if thread.state == ThreadState.RUNNING:
                new_thread = self.scheduler.thread_block(thread, self.processor, now_us)
                if new_thread is not None:
                    self._arm_quantum_for_active(now_us)
                else:
                    self._cancel_quantum_artifacts(reset_quantum_end=True)
            elif thread.state == ThreadState.RUNNABLE:
                self.scheduler.thread_remove(thread, now_us)

            thread.state = ThreadState.TERMINATED
            return task

    # ------------------------------------------------------------------
    # Primary use case
    # ------------------------------------------------------------------
    def what_next(self) -> Dispatch | None:
        """Atomic select+dispatch recommendation matching XNU semantics."""
        with self._lock:
            now_us = self._now_us()
            self._apply_lazy_catchup(now_us)

            active = self.processor.active_thread
            reason: str

            if active is None:
                trace_before = len(self.scheduler.trace_log)
                switch_before = len(self.scheduler.processor_switch_log)

                self._try_dispatch_idle(
                    self.processor,
                    now_us,
                    reason="what_next requested next runnable task",
                )
                active = self.processor.active_thread
                if active is None:
                    return None

                reason = self._derive_selection_reason(trace_before, switch_before)
            else:
                reason = "Task already running; focus block still active."

            task = self.tasks_by_id.get(active.tid)
            if task is None:
                return None

            remaining_us = max(0, self.processor.quantum_end - now_us)
            if remaining_us == 0:
                remaining_us = active.quantum_remaining

            return Dispatch(
                task=task,
                life_area=task.life_area,
                urgency_tier=task.urgency_tier,
                focus_block_hours=self.time_scale.us_to_hours(remaining_us),
                reason=reason,
            )

    # ------------------------------------------------------------------
    # Internal scheduler orchestration
    # ------------------------------------------------------------------
    def _now_us(self) -> int:
        return self.time_scale.now_scheduler_us()

    def _apply_lazy_catchup(self, now_us: int) -> None:
        self._apply_tick_catchup(now_us)

        active = self.processor.active_thread
        if active is None:
            return
        if self.processor.quantum_end <= 0:
            return
        if now_us <= self.processor.quantum_end:
            return

        # Missed focus-block expiration: user likely walked away.
        old_task = self.tasks_by_id.get(active.tid)
        new_thread = self.scheduler.thread_block(active, self.processor, now_us)

        if old_task is not None:
            self.notifier.notify_immediately(
                f"'{old_task.title}' was auto-paused after a missed focus-block end.",
                NotificationEventType.QUANTUM_EXPIRE,
            )

        if new_thread is not None:
            self._arm_quantum_for_active(now_us)
        else:
            self._cancel_quantum_artifacts(reset_quantum_end=True)

    def _apply_tick_catchup(self, now_us: int) -> None:
        if now_us <= self._last_tick_us:
            return

        elapsed = now_us - self._last_tick_us
        due_ticks = elapsed // SCHED_TICK_INTERVAL_US
        if due_ticks <= 0:
            return

        to_apply = min(due_ticks, self.max_catchup_ticks)
        for _ in range(to_apply):
            tick_us = self._last_tick_us + SCHED_TICK_INTERVAL_US
            self.scheduler.sched_tick(tick_us)
            self._last_tick_us = tick_us

        self._arm_tick_timer()

    def _handle_preemption_request(
        self,
        preempt_proc: Processor | None,
        timestamp: int,
        *,
        trigger_when_idle: bool,
    ) -> None:
        if preempt_proc is None:
            return

        if preempt_proc.is_idle and not trigger_when_idle:
            # Keep runnable work queued until an explicit what_next/select step.
            self.scheduler.consume_preemption_reason(preempt_proc)
            return

        old_active = preempt_proc.active_thread
        self._handle_preemption(preempt_proc, timestamp)
        new_active = preempt_proc.active_thread

        if (
            old_active is not None
            and new_active is not None
            and new_active is not old_active
        ):
            old_task = self.tasks_by_id.get(old_active.tid)
            new_task = self.tasks_by_id.get(new_active.tid)
            if old_task is not None and new_task is not None:
                self.notifier.notify_immediately(
                    f"Urgent: '{new_task.title}' should preempt '{old_task.title}'.",
                    NotificationEventType.PREEMPTION,
                )

    def _handle_preemption(self, proc: Processor, timestamp: int) -> None:
        """Port of simulator preemption flow, minus stats tracking."""
        preemption_reason = self.scheduler.consume_preemption_reason(proc)

        if proc.is_idle:
            self._try_dispatch_idle(
                proc,
                timestamp,
                reason=f"preemption signal on idle CPU: {preemption_reason}",
            )
            return

        old_thread = proc.active_thread
        if old_thread is None:
            self._try_dispatch_idle(
                proc,
                timestamp,
                reason=f"preemption signal with no active thread: {preemption_reason}",
            )
            return

        if old_thread.computation_epoch > 0:
            cpu_time = timestamp - old_thread.computation_epoch
            old_thread.total_cpu_us += cpu_time
            old_thread.computation_epoch = 0

            if old_thread.thread_group.sched_clutch is not None:
                cbg = old_thread.thread_group.sched_clutch.sc_clutch_groups[
                    old_thread.th_sched_bucket
                ]
                update_thread_cpu_usage(old_thread, cpu_time, cbg)

        keep_quantum = (
            proc.first_timeslice and proc.starting_pri <= old_thread.sched_pri
        )
        if keep_quantum:
            old_thread.quantum_remaining = max(
                0,
                old_thread.quantum_remaining - (timestamp - proc.last_dispatch_time),
            )
        else:
            old_thread.quantum_remaining = 0

        if old_thread.is_realtime and old_thread.quantum_remaining == 0:
            old_thread.rt_deadline = RT_DEADLINE_QUANTUM_EXPIRED

        old_thread.state = ThreadState.RUNNABLE
        if old_thread.is_timeshare:
            self.scheduler._timeshare_setrun_update(old_thread)

        new_thread, chose_prev = self.scheduler.thread_select(
            proc,
            timestamp,
            prev_thread=old_thread,
        )

        if chose_prev and new_thread is old_thread:
            self.scheduler.thread_dispatch(
                proc,
                old_thread,
                old_thread,
                timestamp,
                reason=(
                    f"preemption requested ({preemption_reason}), but "
                    f"{old_thread.name} remained best eligible thread"
                ),
            )
            self._arm_quantum_for_active(timestamp)
            return

        if new_thread is not None:
            self.scheduler.thread_setrun(old_thread, timestamp, options=SCHED_HEADQ)
            self.scheduler.thread_dispatch(
                proc,
                old_thread,
                new_thread,
                timestamp,
                reason=f"preemption: {preemption_reason}",
            )
            self._arm_quantum_for_active(timestamp)
            return

        self.scheduler.thread_dispatch(
            proc,
            old_thread,
            old_thread,
            timestamp,
            reason=(
                f"preemption requested ({preemption_reason}), but no "
                "better runnable replacement was selected"
            ),
        )
        self._arm_quantum_for_active(timestamp)

    def _try_dispatch_idle(self, proc: Processor, timestamp: int, *, reason: str) -> None:
        selected, _ = self.scheduler.thread_select(proc, timestamp)
        if selected is None:
            self._cancel_quantum_artifacts(reset_quantum_end=True)
            return

        self.scheduler.thread_dispatch(
            proc,
            None,
            selected,
            timestamp,
            reason=reason,
        )
        self._arm_quantum_for_active(timestamp)

    def _arm_quantum_for_active(self, dispatch_timestamp: int) -> None:
        active = self.processor.active_thread
        if active is None:
            self._cancel_quantum_artifacts(reset_quantum_end=True)
            return

        if active.quantum_remaining <= 0:
            active.reset_quantum()

        quantum_end = dispatch_timestamp + active.quantum_remaining
        self.processor.quantum_end = quantum_end

        if not self._enable_timers:
            return

        self._cancel_quantum_artifacts(reset_quantum_end=False)
        task = self.tasks_by_id.get(active.tid)
        task_label = task.title if task is not None else active.name

        due_wall = self.time_scale.scheduler_us_to_wall(quantum_end)
        self._quantum_notification_id = self.notifier.schedule_notification(
            due_wall,
            f"Focus block ended for '{task_label}'. Re-evaluating now.",
            NotificationEventType.QUANTUM_EXPIRE,
        )

        delay_seconds = max(
            0.0,
            (due_wall - self.time_scale.now_wallclock()).total_seconds(),
        )
        self._quantum_timer = Timer(delay_seconds, self._on_quantum_timer, args=(active.tid, quantum_end))
        self._quantum_timer.daemon = True
        self._quantum_timer.start()

    def _on_quantum_timer(self, expected_tid: int, expected_quantum_end: int) -> None:
        with self._lock:
            now_us = self._now_us()
            self._apply_tick_catchup(now_us)

            active = self.processor.active_thread
            if active is None:
                return
            if active.tid != expected_tid:
                return
            if self.processor.quantum_end != expected_quantum_end:
                return

            old_thread = active
            new_thread = self.scheduler.thread_quantum_expire(self.processor, expected_quantum_end)

            if self.processor.active_thread is not None:
                self._arm_quantum_for_active(expected_quantum_end)
            else:
                self._cancel_quantum_artifacts(reset_quantum_end=True)

            if new_thread is None:
                self.notifier.notify_immediately(
                    "No runnable tasks remain after focus-block re-evaluation.",
                    NotificationEventType.QUANTUM_EXPIRE,
                )
                return

            new_task = self.tasks_by_id.get(new_thread.tid)
            old_task = self.tasks_by_id.get(old_thread.tid)

            if new_thread is old_thread:
                label = new_task.title if new_task is not None else old_thread.name
                self.notifier.notify_immediately(
                    f"Keep going on '{label}' — still the best use of your time.",
                    NotificationEventType.QUANTUM_EXPIRE,
                )
                return

            old_label = old_task.title if old_task is not None else old_thread.name
            new_label = new_task.title if new_task is not None else new_thread.name
            self.notifier.notify_immediately(
                f"Switch to '{new_label}' — focus block ended for '{old_label}'.",
                NotificationEventType.QUANTUM_EXPIRE,
            )

    def _arm_tick_timer(self) -> None:
        if not self._enable_timers:
            return

        self._cancel_tick_artifacts()
        next_tick_us = self._last_tick_us + SCHED_TICK_INTERVAL_US

        due_wall = self.time_scale.scheduler_us_to_wall(next_tick_us)
        self._tick_notification_id = self.notifier.schedule_notification(
            due_wall,
            "Scheduler maintenance tick executed.",
            NotificationEventType.SCHED_TICK,
        )

        delay_seconds = max(
            0.0,
            (due_wall - self.time_scale.now_wallclock()).total_seconds(),
        )
        self._tick_timer = Timer(delay_seconds, self._on_tick_timer, args=(next_tick_us,))
        self._tick_timer.daemon = True
        self._tick_timer.start()

    def _on_tick_timer(self, expected_tick_us: int) -> None:
        with self._lock:
            now_us = self._now_us()
            if expected_tick_us <= self._last_tick_us:
                return
            if now_us + 1 < expected_tick_us:
                self._arm_tick_timer()
                return

            self.scheduler.sched_tick(expected_tick_us)
            self._last_tick_us = expected_tick_us
            self._arm_tick_timer()

    def _cancel_quantum_artifacts(self, *, reset_quantum_end: bool) -> None:
        if self._quantum_timer is not None:
            self._quantum_timer.cancel()
            self._quantum_timer = None

        if self._quantum_notification_id is not None:
            self.notifier.cancel_notification(self._quantum_notification_id)
            self._quantum_notification_id = None

        if reset_quantum_end:
            self.processor.quantum_end = 0

    def _cancel_tick_artifacts(self) -> None:
        if self._tick_timer is not None:
            self._tick_timer.cancel()
            self._tick_timer = None

        if self._tick_notification_id is not None:
            self.notifier.cancel_notification(self._tick_notification_id)
            self._tick_notification_id = None

    # ------------------------------------------------------------------
    # Lookup / formatting helpers
    # ------------------------------------------------------------------
    def _derive_selection_reason(self, trace_before: int, switch_before: int) -> str:
        # Prefer thread_select trace because it reflects the internal comparator path.
        if len(self.scheduler.trace_log) > trace_before:
            for line in reversed(self.scheduler.trace_log[trace_before:]):
                if "Select " in line:
                    return line

        if len(self.scheduler.processor_switch_log) > switch_before:
            last = self.scheduler.processor_switch_log[-1]
            marker = "| reason: "
            if marker in last:
                return last.split(marker, 1)[1]

        return "Selected highest-ranked runnable task."

    def _resolve_life_area(self, life_area: LifeArea | int | str) -> LifeArea:
        if isinstance(life_area, LifeArea):
            return life_area

        if isinstance(life_area, int):
            if life_area not in self.life_areas_by_id:
                raise KeyError(f"Unknown life_area id: {life_area}")
            return self.life_areas_by_id[life_area]

        key = self._normalize_name(life_area)
        if key not in self._life_areas_by_name:
            raise KeyError(f"Unknown life_area name: {life_area!r}")
        return self._life_areas_by_name[key]

    def _resolve_task(self, task_id: int | None) -> Task | None:
        if task_id is None:
            active = self.processor.active_thread
            if active is None:
                return None
            return self.tasks_by_id.get(active.tid)
        return self.tasks_by_id.get(task_id)

    def _require_task(self, task_id: int) -> Task:
        task = self.tasks_by_id.get(task_id)
        if task is None:
            raise KeyError(f"Unknown task id: {task_id}")
        return task

    @staticmethod
    def _normalize_name(name: str) -> str:
        return name.strip().lower()

    @staticmethod
    def _thread_name_from_title(title: str) -> str:
        stem = "-".join(title.strip().split())
        return stem.lower()[:48] or "task"
