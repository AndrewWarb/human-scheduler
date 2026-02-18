"""GUI-facing facade for scheduler commands, queries, and diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable, TypeVar

from human_sched.application.runtime import Dispatch, HumanTaskScheduler
from human_sched.domain.life_area import LifeArea
from human_sched.domain.task import Task
from human_sched.domain.urgency import UrgencyTier
from human_sched.gui.contract import CONTRACT_VERSION, GuiAdapterMetadata
from human_sched.gui.events import EventHub, SchedulerEvent
from human_sched.gui.scenarios import available_seed_scenarios
from xnu_sched.thread import ThreadState


T = TypeVar("T")


class SchedulerGuiFacade:
    """Facade that isolates GUI adapters from scheduler internals."""

    __slots__ = (
        "_scheduler",
        "_event_hub",
        "_lock",
        "_last_successful_command_at",
        "_last_command_error",
        "_last_dispatch_task_id",
        "_last_dispatch_at",
        "_last_dispatch_reason",
        "_last_dispatch_decision",
    )

    def __init__(self, scheduler: HumanTaskScheduler, event_hub: EventHub) -> None:
        self._scheduler = scheduler
        self._event_hub = event_hub
        self._lock = RLock()
        self._last_successful_command_at: datetime | None = None
        self._last_command_error: str | None = None
        self._last_dispatch_task_id: int | None = None
        self._last_dispatch_at: datetime | None = None
        self._last_dispatch_reason: str | None = None
        self._last_dispatch_decision: str | None = None

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def create_life_area(self, *, name: str) -> dict[str, Any]:
        def _create() -> dict[str, Any]:
            if not name.strip():
                raise ValueError("Life area name is required")
            area = self._scheduler.create_life_area(name=name)
            self.publish_info(f"Life area '{area.name}' is ready.")
            return self._serialize_life_area(area)

        return self._run_command(_create)

    def delete_life_area(self, *, life_area_id: int) -> dict[str, Any]:
        def _delete() -> dict[str, Any]:
            area, deleted_task_count = self._scheduler.delete_life_area(life_area_id)
            task_word = "task" if deleted_task_count == 1 else "tasks"
            self.publish_info(
                f"Deleted life area '{area.name}' and removed {deleted_task_count} {task_word}.",
            )
            return {
                "life_area": self._serialize_life_area(area),
                "deleted_task_count": deleted_task_count,
            }

        return self._run_command(_delete)

    def rename_life_area(self, *, life_area_id: int, name: str) -> dict[str, Any]:
        def _rename() -> dict[str, Any]:
            area = self._scheduler.rename_life_area(life_area_id, name=name)
            self.publish_info(f"Life area renamed to '{area.name}'.")
            return self._serialize_life_area(area)

        return self._run_command(_rename)

    def create_task(
        self,
        *,
        life_area_id: int,
        title: str,
        urgency_tier: str,
        description: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        def _create() -> dict[str, Any]:
            if not title.strip():
                raise ValueError("Task title is required")
            task = self._scheduler.create_task(
                life_area=life_area_id,
                title=title,
                urgency_tier=urgency_tier,
                description=description,
                notes=notes,
                start_runnable=True,
            )
            self.publish_info(
                f"Task '{task.title}' created in {task.life_area.name} ({task.urgency_tier.label}).",
                related_task_id=task.task_id,
            )
            return self._serialize_task(task)

        return self._run_command(_create)

    def pause_task(self, *, task_id: int) -> dict[str, Any]:
        def _pause() -> dict[str, Any]:
            task = self._scheduler.pause_task(task_id)
            if task is None:
                raise KeyError(f"Unknown task id: {task_id}")
            self.publish_info(f"Paused '{task.title}'.", related_task_id=task.task_id)
            return self._serialize_task(task)

        return self._run_command(_pause)

    def resume_task(self, *, task_id: int) -> dict[str, Any]:
        def _resume() -> dict[str, Any]:
            task = self._scheduler.resume_task(task_id)
            self.publish_info(f"Resumed '{task.title}'.", related_task_id=task.task_id)
            return self._serialize_task(task)

        return self._run_command(_resume)

    def complete_task(self, *, task_id: int) -> dict[str, Any]:
        def _complete() -> dict[str, Any]:
            task = self._scheduler.complete_task(task_id)
            if task is None:
                raise KeyError(f"Unknown task id: {task_id}")
            self.publish_info(f"Completed '{task.title}'.", related_task_id=task.task_id)
            return self._serialize_task(task)

        return self._run_command(_complete)

    def delete_task(self, *, task_id: int) -> dict[str, Any]:
        def _delete() -> dict[str, Any]:
            task = self._scheduler.delete_task(task_id)
            if self._last_dispatch_task_id == task.task_id:
                self._last_dispatch_task_id = None
                self._last_dispatch_at = None
                self._last_dispatch_reason = None
                self._last_dispatch_decision = None
            self.publish_info(f"Deleted '{task.title}'.", related_task_id=task.task_id)
            return self._serialize_task(task)

        return self._run_command(_delete)

    def reset_simulation(self) -> dict[str, Any]:
        def _reset() -> dict[str, Any]:
            reset_task_count = self._scheduler.reset_simulation()
            task_word = "task" if reset_task_count == 1 else "tasks"
            self._last_dispatch_task_id = None
            self._last_dispatch_at = None
            self._last_dispatch_reason = None
            self._last_dispatch_decision = None
            self.publish_info(
                f"Simulation reset to t=0. Re-queued {reset_task_count} {task_word}.",
            )
            return {
                "status": "ok",
                "reset_task_count": reset_task_count,
            }

        return self._run_command(_reset)

    def what_next(self) -> dict[str, Any] | None:
        def _select() -> dict[str, Any] | None:
            before_snapshot = self._scheduler.get_dispatch_snapshot()
            before_task = before_snapshot["active_task"]
            before_tid = before_task.task_id if isinstance(before_task, Task) else None

            dispatch = self._scheduler.what_next()
            if dispatch is None:
                self.publish_info("No runnable tasks. Create or resume a task to continue.")
                return None

            snapshot = self._scheduler.get_dispatch_snapshot()
            dto = self._serialize_dispatch(dispatch, before_tid=before_tid, snapshot=snapshot)
            self.publish_info(
                f"What Next: {dto['decision']} -> '{dispatch.task.title}'.",
                related_task_id=dispatch.task.task_id,
            )
            return dto

        return self._run_command(_select)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def list_life_areas(self) -> list[dict[str, Any]]:
        with self._lock:
            areas = sorted(self._scheduler.list_life_areas(), key=lambda area: area.life_area_id)
            return [self._serialize_life_area(area) for area in areas]

    def list_tasks(
        self,
        *,
        life_area_id: int | None = None,
        urgency_tier: str | None = None,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            tasks = list(self._scheduler.list_tasks())

            if life_area_id is not None:
                tasks = [task for task in tasks if task.life_area.life_area_id == life_area_id]

            if urgency_tier:
                normalized_urgency = UrgencyTier.from_value(urgency_tier)
                tasks = [task for task in tasks if task.urgency_tier == normalized_urgency]

            if state:
                normalized_state = state.strip().upper()
                tasks = [task for task in tasks if task.state.name == normalized_state]

            tasks.sort(key=lambda task: task.created_at, reverse=True)
            return [self._serialize_task(task) for task in tasks]

    def current_dispatch(self) -> dict[str, Any] | None:
        with self._lock:
            snapshot = self._scheduler.get_dispatch_snapshot()
            task = snapshot["active_task"]
            if not isinstance(task, Task):
                self._last_dispatch_task_id = None
                self._last_dispatch_at = None
                self._last_dispatch_reason = None
                self._last_dispatch_decision = None
                return None

            now_us = int(snapshot["now_us"])
            quantum_end_us = int(snapshot["quantum_end_us"])
            remaining_us = max(0, quantum_end_us - now_us)

            switch_reason = snapshot["last_switch_reason"]
            switch_timestamp_us = snapshot["last_switch_timestamp_us"]

            if self._last_dispatch_task_id != task.task_id:
                self._last_dispatch_task_id = task.task_id
                self._last_dispatch_reason = (
                    switch_reason if isinstance(switch_reason, str) else "Selected highest-ranked runnable task."
                )
                dispatch_wall = self._wall_now()
                if isinstance(switch_timestamp_us, int):
                    dispatch_wall = self._scheduler.time_scale.scheduler_us_to_wall(switch_timestamp_us)
                self._last_dispatch_at = dispatch_wall
                self._last_dispatch_decision = "switch"

            return {
                "task": self._serialize_task(task),
                "life_area": self._serialize_life_area(task.life_area),
                "urgency_tier": task.urgency_tier.value,
                "focus_block_hours": self._scheduler.time_scale.us_to_hours(remaining_us),
                "focus_block_end_at": self._iso(self._scheduler.time_scale.scheduler_us_to_wall(quantum_end_us)),
                "reason": self._last_dispatch_reason or "Task already running.",
                "decision": self._last_dispatch_decision or "continuation",
                "dispatched_at": self._iso(self._last_dispatch_at or self._wall_now()),
            }

    def list_events(self, *, limit: int = 200) -> list[dict[str, Any]]:
        events = self._event_hub.list_recent(limit=limit)
        return [self._serialize_event(event) for event in events]

    def subscribe_events(self, *, after_event_id: int | None = None) -> int:
        return self._event_hub.subscribe(after_event_id=after_event_id)

    def unsubscribe_events(self, subscriber_id: int) -> None:
        self._event_hub.unsubscribe(subscriber_id)

    def next_event(self, subscriber_id: int, *, timeout_seconds: float | None = None) -> dict[str, Any] | None:
        event = self._event_hub.next_event(subscriber_id, timeout_seconds=timeout_seconds)
        if event is None:
            return None
        return self._serialize_event(event)

    def app_settings(self) -> dict[str, Any]:
        return {
            "urgency_tiers": [
                {
                    "value": tier.value,
                    "label": tier.label,
                }
                for tier in UrgencyTier
            ],
            "seed_scenarios": available_seed_scenarios(),
            "thread_states": [state.name.lower() for state in ThreadState],
        }

    def diagnostics(
        self,
        *,
        adapter_metadata: GuiAdapterMetadata,
        base_url: str,
        event_stream_status: str,
        event_stream_active_clients: int,
        event_stream_retried_writes: int,
        event_stream_dropped_clients: int,
    ) -> dict[str, Any]:
        with self._lock:
            last_event = self._event_hub.last_event
            last_event_timestamp = self._iso(last_event.timestamp) if last_event else None
            lag_ms = None
            if last_event is not None:
                lag_ms = int((self._wall_now() - last_event.timestamp).total_seconds() * 1000)

            return {
                "adapter_name": adapter_metadata.name,
                "adapter_version": adapter_metadata.version,
                "contract_version": CONTRACT_VERSION,
                "scheduler_connection_status": "connected",
                "scheduler_base_url": base_url,
                "event_stream_status": event_stream_status,
                "event_stream_active_clients": event_stream_active_clients,
                "last_event_timestamp": last_event_timestamp,
                "event_lag_ms": lag_ms,
                "last_successful_command_time": self._iso(self._last_successful_command_at),
                "last_command_error": self._last_command_error,
                "dropped_event_count": self._event_hub.dropped_event_count,
                "event_stream_dropped_clients": event_stream_dropped_clients,
                "event_stream_retried_writes": event_stream_retried_writes,
            }

    def metadata(self, *, adapter_metadata: GuiAdapterMetadata, base_url: str) -> dict[str, Any]:
        return {
            "adapter": {
                "name": adapter_metadata.name,
                "version": adapter_metadata.version,
                "capabilities": list(adapter_metadata.capabilities),
            },
            "contract_version": CONTRACT_VERSION,
            "base_url": base_url,
        }

    def publish_info(self, message: str, *, related_task_id: int | None = None) -> None:
        self._event_hub.publish(
            event_type="info",
            message=message,
            related_task_id=related_task_id,
            source="facade",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _run_command(self, callback: Callable[[], T]) -> T:
        with self._lock:
            try:
                result = callback()
            except Exception as exc:
                self._last_command_error = str(exc)
                raise
            self._last_successful_command_at = self._wall_now()
            self._last_command_error = None
            return result

    def _serialize_task(self, task: Task) -> dict[str, Any]:
        return {
            "id": task.task_id,
            "title": task.title,
            "life_area_id": task.life_area.life_area_id,
            "life_area_name": task.life_area.name,
            "urgency_tier": task.urgency_tier.value,
            "urgency_label": task.urgency_tier.label,
            "state": task.state.name.lower(),
            "description": task.description,
            "notes": task.notes,
            "due_at": self._iso(task.due_at),
            "created_at": self._iso(task.created_at),
        }

    def _serialize_life_area(self, life_area: LifeArea) -> dict[str, Any]:
        return {
            "id": life_area.life_area_id,
            "name": life_area.name,
            "task_count": len(life_area.task_ids),
            "interactivity_scores": life_area.interactivity_scores(),
        }

    def _serialize_dispatch(
        self,
        dispatch: Dispatch,
        *,
        before_tid: int | None,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        now_us = int(snapshot["now_us"])
        quantum_end_us = int(snapshot["quantum_end_us"])
        remaining_us = max(0, quantum_end_us - now_us)

        decision = "start"
        if before_tid is not None:
            decision = "continuation" if before_tid == dispatch.task.task_id else "switch"

        self._last_dispatch_task_id = dispatch.task.task_id
        self._last_dispatch_reason = dispatch.reason
        self._last_dispatch_decision = decision

        switch_timestamp_us = snapshot["last_switch_timestamp_us"]
        if isinstance(switch_timestamp_us, int):
            self._last_dispatch_at = self._scheduler.time_scale.scheduler_us_to_wall(switch_timestamp_us)
        else:
            self._last_dispatch_at = self._wall_now()

        return {
            "task": self._serialize_task(dispatch.task),
            "life_area": self._serialize_life_area(dispatch.life_area),
            "urgency_tier": dispatch.urgency_tier.value,
            "focus_block_hours": self._scheduler.time_scale.us_to_hours(remaining_us),
            "focus_block_end_at": self._iso(self._scheduler.time_scale.scheduler_us_to_wall(quantum_end_us)),
            "reason": dispatch.reason,
            "decision": decision,
            "dispatched_at": self._iso(self._last_dispatch_at),
        }

    @staticmethod
    def _serialize_event(event: SchedulerEvent) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "message": event.message,
            "timestamp": event.timestamp.isoformat(),
            "related_task_id": event.related_task_id,
            "source": event.source,
        }

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    @staticmethod
    def _wall_now() -> datetime:
        return datetime.now(timezone.utc)
