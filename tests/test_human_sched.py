from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from human_sched.adapters.time_scale import TimeScaleAdapter, TimeScaleConfig, load_time_scale_config
from human_sched.application.runtime import HumanTaskScheduler
from human_sched.domain.urgency import UrgencyTier
from human_sched.ports.notifications import NotificationEventType
from xnu_sched.thread import ThreadState


class FakeNotifier:
    def __init__(self) -> None:
        self.scheduled: list[tuple[str, datetime, str, NotificationEventType]] = []
        self.cancelled: list[str] = []
        self.immediate: list[tuple[str, NotificationEventType]] = []
        self._next_id = 0

    def schedule_notification(
        self,
        at: datetime,
        message: str,
        event_type: NotificationEventType,
    ) -> str:
        notification_id = f"n{self._next_id}"
        self._next_id += 1
        self.scheduled.append((notification_id, at, message, event_type))
        return notification_id

    def cancel_notification(self, notification_id: str) -> None:
        self.cancelled.append(notification_id)

    def notify_immediately(self, message: str, event_type: NotificationEventType) -> None:
        self.immediate.append((message, event_type))


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def now(self) -> datetime:
        return self.current

    def advance_hours(self, hours: float) -> None:
        self.current = self.current + timedelta(hours=hours)


class HumanSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.notifier = FakeNotifier()
        self.time_scale = TimeScaleAdapter(
            config=TimeScaleConfig(hours_per_us=0.00025, max_catchup_ticks=4),
            wall_epoch=self.clock.now(),
            now_provider=self.clock.now,
        )
        self.scheduler = HumanTaskScheduler(
            notifier=self.notifier,
            time_scale=self.time_scale,
            enable_timers=False,
        )

    def tearDown(self) -> None:
        self.scheduler.close()

    def test_create_and_select_next_task(self) -> None:
        area = self.scheduler.create_life_area("Work")
        self.scheduler.create_task(
            life_area=area,
            title="Write report",
            urgency_tier=UrgencyTier.NORMAL,
        )

        dispatch = self.scheduler.what_next()
        self.assertIsNotNone(dispatch)
        assert dispatch is not None

        self.assertEqual(dispatch.task.title, "Write report")
        self.assertEqual(dispatch.life_area.name, "Work")
        self.assertEqual(dispatch.urgency_tier, UrgencyTier.NORMAL)
        self.assertAlmostEqual(dispatch.focus_block_hours, 1.5, places=6)

    def test_higher_urgency_wins(self) -> None:
        work = self.scheduler.create_life_area("Work")
        home = self.scheduler.create_life_area("Home")

        self.scheduler.create_task(
            life_area=work,
            title="Write docs",
            urgency_tier=UrgencyTier.NORMAL,
        )
        self.scheduler.create_task(
            life_area=home,
            title="File taxes",
            urgency_tier=UrgencyTier.CRITICAL,
        )

        dispatch = self.scheduler.what_next()
        self.assertIsNotNone(dispatch)
        assert dispatch is not None
        self.assertEqual(dispatch.task.title, "File taxes")
        self.assertEqual(dispatch.urgency_tier, UrgencyTier.CRITICAL)

    def test_pause_resume_complete_lifecycle(self) -> None:
        area = self.scheduler.create_life_area("Personal")
        normal = self.scheduler.create_task(
            life_area=area,
            title="Deep work",
            urgency_tier=UrgencyTier.NORMAL,
        )
        maintenance = self.scheduler.create_task(
            life_area=area,
            title="Sort emails",
            urgency_tier=UrgencyTier.MAINTENANCE,
        )

        first = self.scheduler.what_next()
        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(first.task.task_id, normal.task_id)

        paused = self.scheduler.pause_task(normal.task_id)
        self.assertIsNotNone(paused)
        assert paused is not None
        self.assertEqual(paused.thread.state, ThreadState.WAITING)

        second = self.scheduler.what_next()
        self.assertIsNotNone(second)
        assert second is not None
        self.assertEqual(second.task.task_id, maintenance.task_id)

        resumed = self.scheduler.resume_task(normal.task_id)
        self.assertEqual(resumed.thread.state, ThreadState.RUNNING)

        completed = self.scheduler.complete_task(normal.task_id)
        self.assertIsNotNone(completed)
        assert completed is not None
        self.assertEqual(completed.thread.state, ThreadState.TERMINATED)

    def test_delete_life_area_removes_its_tasks(self) -> None:
        work = self.scheduler.create_life_area("Work")
        home = self.scheduler.create_life_area("Home")
        self.scheduler.create_task(
            life_area=work,
            title="Write report",
            urgency_tier=UrgencyTier.NORMAL,
        )
        keep_task = self.scheduler.create_task(
            life_area=home,
            title="Laundry",
            urgency_tier=UrgencyTier.IMPORTANT,
        )

        deleted_area, deleted_task_count = self.scheduler.delete_life_area(work.life_area_id)

        self.assertEqual(deleted_area.life_area_id, work.life_area_id)
        self.assertEqual(deleted_task_count, 1)
        self.assertEqual(len(self.scheduler.list_life_areas()), 1)
        self.assertEqual(self.scheduler.list_life_areas()[0].life_area_id, home.life_area_id)
        self.assertEqual(len(self.scheduler.list_tasks()), 1)
        self.assertEqual(self.scheduler.list_tasks()[0].task_id, keep_task.task_id)

    def test_delete_task_removes_it_from_scheduler(self) -> None:
        area = self.scheduler.create_life_area("Work")
        first = self.scheduler.create_task(
            life_area=area,
            title="Prepare launch notes",
            urgency_tier=UrgencyTier.CRITICAL,
        )
        second = self.scheduler.create_task(
            life_area=area,
            title="Tidy backlog",
            urgency_tier=UrgencyTier.MAINTENANCE,
        )

        dispatch = self.scheduler.what_next()
        self.assertIsNotNone(dispatch)
        assert dispatch is not None
        self.assertEqual(dispatch.task.task_id, first.task_id)

        deleted = self.scheduler.delete_task(first.task_id)

        self.assertEqual(deleted.task_id, first.task_id)
        self.assertNotIn(first.task_id, self.scheduler.tasks_by_id)
        self.assertNotIn(first.task_id, area.task_ids)
        self.assertEqual(len(self.scheduler.list_tasks()), 1)
        self.assertEqual(self.scheduler.list_tasks()[0].task_id, second.task_id)

    def test_fixpri_sleep_task_auto_runs_only_during_sleep_window(self) -> None:
        # Outside the configured window (21:00-04:00), task should stay blocked.
        self.clock.advance_hours(20)
        area = self.scheduler.create_life_area("Health")
        sleep = self.scheduler.create_task(
            life_area=area,
            title="Sleep",
            urgency_tier=UrgencyTier.CRITICAL,
            active_window_start_local="21:00",
            active_window_end_local="04:00",
        )

        before_window = self.scheduler.what_next()
        self.assertIsNone(before_window)
        self.assertEqual(sleep.thread.state, ThreadState.WAITING)

        # During the sleep window, Sleep should auto-wake and dispatch.
        self.clock.advance_hours(1.5)
        in_window = self.scheduler.what_next()
        self.assertIsNotNone(in_window)
        assert in_window is not None
        self.assertEqual(in_window.task.task_id, sleep.task_id)
        self.assertEqual(sleep.thread.state, ThreadState.RUNNING)

        # After 04:00, Sleep should auto-block again.
        self.clock.advance_hours(7.0)
        after_window = self.scheduler.what_next()
        self.assertIsNone(after_window)
        self.assertEqual(sleep.thread.state, ThreadState.WAITING)

    def test_task_window_can_be_updated_after_task_creation(self) -> None:
        self.clock.advance_hours(20)
        area = self.scheduler.create_life_area("Health")
        sleep = self.scheduler.create_task(
            life_area=area,
            title="Sleep",
            urgency_tier=UrgencyTier.CRITICAL,
        )

        baseline = self.scheduler.what_next()
        self.assertIsNotNone(baseline)
        self.assertEqual(sleep.thread.state, ThreadState.RUNNING)

        updated = self.scheduler.set_task_active_window(
            sleep.task_id,
            active_window_start_local="21:00",
            active_window_end_local="04:00",
        )
        self.assertEqual(updated.active_window_start_minute, 21 * 60)
        self.assertEqual(updated.active_window_end_minute, 4 * 60)
        self.assertEqual(sleep.thread.state, ThreadState.WAITING)
        self.assertIsNone(self.scheduler.what_next())

        self.clock.advance_hours(1.25)
        in_window = self.scheduler.what_next()
        self.assertIsNotNone(in_window)
        self.assertEqual(sleep.thread.state, ThreadState.RUNNING)

        cleared = self.scheduler.set_task_active_window(
            sleep.task_id,
            active_window_start_local=None,
            active_window_end_local=None,
        )
        self.assertIsNone(cleared.active_window_start_minute)
        self.assertIsNone(cleared.active_window_end_minute)

    def test_task_window_requires_critical_urgency_and_both_times(self) -> None:
        area = self.scheduler.create_life_area("Work")

        with self.assertRaises(ValueError):
            self.scheduler.create_task(
                life_area=area,
                title="Windowed normal task",
                urgency_tier=UrgencyTier.NORMAL,
                active_window_start_local="09:00",
                active_window_end_local="11:00",
            )

        with self.assertRaises(ValueError):
            self.scheduler.create_task(
                life_area=area,
                title="Broken window task",
                urgency_tier=UrgencyTier.CRITICAL,
                active_window_start_local="09:00",
                active_window_end_local=None,
            )

        normal = self.scheduler.create_task(
            life_area=area,
            title="Inbox zero",
            urgency_tier=UrgencyTier.NORMAL,
        )
        with self.assertRaises(ValueError):
            self.scheduler.set_task_active_window(
                normal.task_id,
                active_window_start_local="09:00",
                active_window_end_local="11:00",
            )

        critical = self.scheduler.create_task(
            life_area=area,
            title="Sleep",
            urgency_tier=UrgencyTier.CRITICAL,
        )
        with self.assertRaises(ValueError):
            self.scheduler.set_task_active_window(
                critical.task_id,
                active_window_start_local="09:00",
                active_window_end_local="09:00",
            )

    def test_reset_simulation_requeues_unfinished_tasks(self) -> None:
        area = self.scheduler.create_life_area("Work")
        active = self.scheduler.create_task(
            life_area=area,
            title="Ship release notes",
            urgency_tier=UrgencyTier.CRITICAL,
        )
        done = self.scheduler.create_task(
            life_area=area,
            title="Archive old docs",
            urgency_tier=UrgencyTier.MAINTENANCE,
        )

        dispatch = self.scheduler.what_next()
        self.assertIsNotNone(dispatch)
        self.scheduler.complete_task(done.task_id)

        reset_count = self.scheduler.reset_simulation()

        self.assertEqual(reset_count, 1)
        self.assertEqual(active.thread.state, ThreadState.RUNNABLE)
        self.assertEqual(done.thread.state, ThreadState.TERMINATED)
        self.assertIsNone(self.scheduler.processor.active_thread)
        self.assertEqual(self.scheduler.processor.quantum_end, 0)

    def test_rename_life_area_updates_name_lookup(self) -> None:
        area = self.scheduler.create_life_area("Study")
        renamed = self.scheduler.rename_life_area(area.life_area_id, name="Deep Study")

        self.assertEqual(renamed.name, "Deep Study")
        self.assertEqual(renamed.thread_group.name, "Deep Study")
        with self.assertRaises(KeyError):
            self.scheduler.create_task(
                life_area="Study",
                title="Old name should fail",
                urgency_tier=UrgencyTier.NORMAL,
            )
        task = self.scheduler.create_task(
            life_area="Deep Study",
            title="New name works",
            urgency_tier=UrgencyTier.NORMAL,
        )
        self.assertEqual(task.life_area.life_area_id, area.life_area_id)

    def test_persistence_round_trip_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            notifier = FakeNotifier()
            clock = FakeClock(datetime(2026, 2, 1, tzinfo=timezone.utc))
            time_scale = TimeScaleAdapter(
                config=TimeScaleConfig(hours_per_us=0.00025, max_catchup_ticks=4),
                wall_epoch=clock.now(),
                now_provider=clock.now,
            )

            scheduler_a = HumanTaskScheduler(
                notifier=notifier,
                time_scale=time_scale,
                enable_timers=False,
                persistence_dir=temp_dir,
            )
            try:
                area = scheduler_a.create_life_area("Work")
                scheduler_a.rename_life_area(area.life_area_id, name="Deep Work")
                scheduler_a.create_task(
                    life_area="Deep Work",
                    title="Write architecture note",
                    urgency_tier=UrgencyTier.IMPORTANT,
                    start_runnable=False,
                )
            finally:
                scheduler_a.close()

            scheduler_b = HumanTaskScheduler(
                notifier=FakeNotifier(),
                time_scale=time_scale,
                enable_timers=False,
                persistence_dir=temp_dir,
            )
            try:
                areas = scheduler_b.list_life_areas()
                tasks = scheduler_b.list_tasks()
                self.assertEqual(len(areas), 1)
                self.assertEqual(areas[0].name, "Deep Work")
                self.assertEqual(len(tasks), 1)
                self.assertEqual(tasks[0].title, "Write architecture note")
                self.assertEqual(tasks[0].life_area.name, "Deep Work")
                self.assertEqual(tasks[0].state, ThreadState.WAITING)
            finally:
                scheduler_b.close()

    def test_persistence_loads_legacy_life_area_description_field(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            life_areas_path = Path(temp_dir) / "life_areas.json"
            tasks_path = Path(temp_dir) / "tasks.json"
            life_areas_path.write_text(
                json.dumps(
                    [
                        {
                            "id": 1,
                            "name": "Work",
                            "description": "legacy metadata",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            tasks_path.write_text("[]", encoding="utf-8")

            scheduler = HumanTaskScheduler(
                notifier=FakeNotifier(),
                time_scale=self.time_scale,
                enable_timers=False,
                persistence_dir=temp_dir,
            )
            try:
                areas = scheduler.list_life_areas()
                self.assertEqual(len(areas), 1)
                self.assertEqual(areas[0].name, "Work")
            finally:
                scheduler.close()

    def test_lazy_catchup_auto_pauses_after_missed_quantum(self) -> None:
        area = self.scheduler.create_life_area("Health")
        task = self.scheduler.create_task(
            life_area=area,
            title="Workout",
            urgency_tier=UrgencyTier.NORMAL,
        )

        dispatch = self.scheduler.what_next()
        self.assertIsNotNone(dispatch)
        self.assertEqual(task.thread.state, ThreadState.RUNNING)

        # DF quantum at default scale: 1.5h. Move beyond that without interaction.
        self.clock.advance_hours(2.0)
        result = self.scheduler.what_next()

        self.assertIsNone(result)
        self.assertEqual(task.thread.state, ThreadState.WAITING)
        self.assertTrue(
            any("auto-paused" in msg for msg, _ in self.notifier.immediate),
            "Expected missed-quantum auto-pause notification",
        )

    def test_time_scale_config_loading(self) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("TIME_SCALE_HOURS_PER_US=0.001\n")
            f.write("MAX_CATCHUP_TICKS=7\n")
            path = f.name

        config = load_time_scale_config(path)
        self.assertEqual(config.hours_per_us, 0.001)
        self.assertEqual(config.max_catchup_ticks, 7)

    def test_change_urgency_runnable_task_moves_to_higher_bucket(self) -> None:
        area = self.scheduler.create_life_area("Work")
        task = self.scheduler.create_task(
            life_area=area,
            title="Report",
            urgency_tier=UrgencyTier.NORMAL,
        )
        self.assertEqual(task.urgency_tier, UrgencyTier.NORMAL)
        self.assertEqual(task.thread.state, ThreadState.RUNNABLE)

        result = self.scheduler.change_task_urgency(
            task.task_id, UrgencyTier.IMPORTANT
        )

        self.assertEqual(result.urgency_tier, UrgencyTier.IMPORTANT)
        self.assertEqual(
            result.thread.base_pri, UrgencyTier.IMPORTANT.base_priority
        )
        self.assertEqual(
            result.thread.sched_pri, UrgencyTier.IMPORTANT.base_priority
        )
        # Thread should be re-enqueued as runnable (or running if selected).
        self.assertIn(
            result.thread.state,
            (ThreadState.RUNNABLE, ThreadState.RUNNING),
        )

    def test_change_urgency_running_task_evicts_and_reenqueues(self) -> None:
        area = self.scheduler.create_life_area("Work")
        task = self.scheduler.create_task(
            life_area=area,
            title="Coding",
            urgency_tier=UrgencyTier.NORMAL,
        )
        # Dispatch so the thread becomes RUNNING.
        dispatch = self.scheduler.what_next()
        self.assertIsNotNone(dispatch)
        self.assertEqual(task.thread.state, ThreadState.RUNNING)

        result = self.scheduler.change_task_urgency(
            task.task_id, UrgencyTier.IMPORTANT
        )

        self.assertEqual(result.urgency_tier, UrgencyTier.IMPORTANT)
        self.assertEqual(
            result.thread.base_pri, UrgencyTier.IMPORTANT.base_priority
        )
        # After evict + re-enqueue, thread should be active again
        # (only task, so it gets selected).
        self.assertIn(
            result.thread.state,
            (ThreadState.RUNNABLE, ThreadState.RUNNING),
        )

    def test_change_urgency_waiting_task_updates_params(self) -> None:
        area = self.scheduler.create_life_area("Home")
        task = self.scheduler.create_task(
            life_area=area,
            title="Organize",
            urgency_tier=UrgencyTier.NORMAL,
        )
        self.scheduler.pause_task(task.task_id)
        self.assertEqual(task.thread.state, ThreadState.WAITING)

        result = self.scheduler.change_task_urgency(
            task.task_id, UrgencyTier.IMPORTANT
        )

        self.assertEqual(result.urgency_tier, UrgencyTier.IMPORTANT)
        self.assertEqual(
            result.thread.base_pri, UrgencyTier.IMPORTANT.base_priority
        )
        self.assertEqual(
            result.thread.sched_pri, UrgencyTier.IMPORTANT.base_priority
        )
        # Still waiting — not placed in any runqueue.
        self.assertEqual(result.thread.state, ThreadState.WAITING)

        # Resume should use new priority.
        self.scheduler.resume_task(task.task_id)
        self.assertIn(
            task.thread.state,
            (ThreadState.RUNNABLE, ThreadState.RUNNING),
        )

    def test_change_urgency_completed_task_raises(self) -> None:
        area = self.scheduler.create_life_area("Home")
        task = self.scheduler.create_task(
            life_area=area,
            title="Done item",
            urgency_tier=UrgencyTier.NORMAL,
        )
        self.scheduler.complete_task(task.task_id)
        self.assertEqual(task.thread.state, ThreadState.TERMINATED)

        with self.assertRaises(ValueError):
            self.scheduler.change_task_urgency(
                task.task_id, UrgencyTier.IMPORTANT
            )

    def test_change_urgency_noop_when_same_tier(self) -> None:
        area = self.scheduler.create_life_area("Work")
        task = self.scheduler.create_task(
            life_area=area,
            title="Steady",
            urgency_tier=UrgencyTier.NORMAL,
        )
        old_base = task.thread.base_pri

        result = self.scheduler.change_task_urgency(
            task.task_id, UrgencyTier.NORMAL
        )

        self.assertEqual(result.urgency_tier, UrgencyTier.NORMAL)
        self.assertEqual(result.thread.base_pri, old_base)


if __name__ == "__main__":
    unittest.main()
