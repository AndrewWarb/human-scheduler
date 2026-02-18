from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone

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
                area = scheduler_a.create_life_area("Work", description="Career lane")
                scheduler_a.rename_life_area(area.life_area_id, name="Deep Work")
                scheduler_a.create_task(
                    life_area="Deep Work",
                    title="Write architecture note",
                    urgency_tier=UrgencyTier.IMPORTANT,
                    description="Two-page draft",
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


if __name__ == "__main__":
    unittest.main()
