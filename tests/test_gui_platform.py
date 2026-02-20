from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from human_sched.application.runtime import HumanTaskScheduler
from human_sched.gui.adapters import create_adapter
from human_sched.gui.config import GuiConfig
from human_sched.gui.contract import GuiAdapterMetadata
from human_sched.gui.events import EventHub
from human_sched.gui.facade import SchedulerGuiFacade
from human_sched.gui.host import GuiHost
from human_sched.gui.http_service import SchedulerHttpService
from human_sched.gui.notifier import EventingNotifier


class GuiPlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.event_hub = EventHub()
        self.scheduler = HumanTaskScheduler(
            notifier=EventingNotifier(self.event_hub),
            enable_timers=False,
        )
        self.facade = SchedulerGuiFacade(self.scheduler, self.event_hub)

    def tearDown(self) -> None:
        self.scheduler.close()

    def test_unknown_adapter_fails_fast(self) -> None:
        config = GuiConfig(adapter_name="unknown")
        with self.assertRaises(ValueError):
            create_adapter("unknown", facade=self.facade, config=config)

    def test_facade_exposes_dispatch_and_diagnostics(self) -> None:
        area = self.facade.create_life_area(name="Work")
        self.facade.create_task(
            life_area_id=int(area["id"]),
            title="Draft PRD",
            urgency_tier="important",
        )

        dispatch = self.facade.what_next()
        self.assertIsNotNone(dispatch)
        assert dispatch is not None

        self.assertEqual(dispatch["task"]["title"], "Draft PRD")
        self.assertIn(dispatch["decision"], {"start", "switch", "continuation"})

        diagnostics = self.facade.diagnostics(
            adapter_metadata=GuiAdapterMetadata(name="nextjs", version="1.0.0"),
            base_url="http://127.0.0.1:8765",
            event_stream_status="idle",
            event_stream_active_clients=0,
            event_stream_retried_writes=0,
            event_stream_dropped_clients=0,
        )
        self.assertEqual(diagnostics["scheduler_connection_status"], "connected")
        self.assertEqual(diagnostics["scheduler_base_url"], "http://127.0.0.1:8765")

    def test_http_service_diagnostics_payload(self) -> None:
        area = self.facade.create_life_area(name="Home")
        self.facade.create_task(
            life_area_id=int(area["id"]),
            title="Run laundry",
            urgency_tier="normal",
        )

        dispatch = self.facade.what_next()
        self.assertIsNotNone(dispatch)

        service = SchedulerHttpService(
            facade=self.facade,
            metadata=GuiAdapterMetadata(name="nextjs", version="1.0.0"),
            host="127.0.0.1",
            port=8765,
            static_dir=Path("human_sched/gui/nextjs_site/out"),
        )

        payload = service.diagnostics_payload()
        self.assertEqual(payload["scheduler_connection_status"], "connected")
        self.assertEqual(payload["scheduler_base_url"], "http://127.0.0.1:8765")
        self.assertEqual(payload["event_stream_status"], "idle")

    def test_scheduler_state_includes_quantum_metadata(self) -> None:
        area = self.facade.create_life_area(name="Work")
        created = self.facade.create_task(
            life_area_id=int(area["id"]),
            title="Prepare notes",
            urgency_tier="normal",
        )
        self.assertIsNotNone(self.facade.what_next())

        state = self.facade.scheduler_state()
        self.assertIn("quantum_remaining_us", state)
        self.assertIn("now_hours", state)
        self.assertIn("quantum_total_us", state)
        self.assertIn("quantum_remaining_hours", state)
        self.assertIn("quantum_total_hours", state)
        self.assertIn("warp_budget_bucket", state)
        self.assertIn("warp_budget_remaining_us", state)
        self.assertIn("warp_budget_total_us", state)
        self.assertIn("warp_budget_remaining_hours", state)
        self.assertIn("warp_budget_total_hours", state)
        self.assertIn("warp_budgets", state)
        self.assertIn("edf_deadline_bucket", state)
        self.assertIn("edf_deadline_us", state)
        self.assertIn("edf_deadline_remaining_us", state)
        self.assertIn("edf_deadline_remaining_hours", state)
        self.assertIn("edf_deadline_at", state)
        self.assertIn("edf_deadlines", state)
        self.assertGreater(state["quantum_total_us"], 0)
        self.assertGreater(state["quantum_total_hours"], 0.0)
        self.assertIsNotNone(state["warp_budget_bucket"])
        self.assertGreater(state["warp_budget_total_us"], 0)
        self.assertGreater(state["warp_budget_total_hours"], 0.0)
        self.assertGreater(len(state["warp_budgets"]), 0)
        self.assertIn("bucket", state["warp_budgets"][0])
        self.assertIn("remaining_us", state["warp_budgets"][0])
        self.assertIn("total_us", state["warp_budgets"][0])
        self.assertGreater(len(state["edf_deadlines"]), 0)
        self.assertIn("bucket", state["edf_deadlines"][0])
        self.assertIn("deadline_us", state["edf_deadlines"][0])
        self.assertIn("deadline_remaining_us", state["edf_deadlines"][0])

        thread_rows = state["threads"]
        row = next((t for t in thread_rows if t["task_id"] == int(created["id"])), None)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertIn("sched_bucket", row)
        self.assertIn("quantum_base_us", row)
        self.assertIn("quantum_remaining_us", row)
        self.assertIn("quantum_base_hours", row)
        self.assertIn("quantum_remaining_hours", row)
        self.assertIn("cpu_usage_hours", row)
        self.assertIn("run_queue_rank", row)
        self.assertIsInstance(row["cpu_usage_hours"], (int, float))
        self.assertGreater(row["quantum_base_us"], 0)
        self.assertGreater(row["quantum_base_hours"], 0.0)

    def test_scheduler_state_reports_run_queue_ranks_for_runnable_threads(self) -> None:
        area = self.facade.create_life_area(name="Work")
        self.facade.create_task(
            life_area_id=int(area["id"]),
            title="Task A",
            urgency_tier="important",
        )
        self.facade.create_task(
            life_area_id=int(area["id"]),
            title="Task B",
            urgency_tier="important",
        )
        self.facade.create_task(
            life_area_id=int(area["id"]),
            title="Task C",
            urgency_tier="important",
        )
        self.assertIsNotNone(self.facade.what_next())

        state = self.facade.scheduler_state()
        runnable = [
            row
            for row in state["threads"]
            if row["state"] in {"running", "runnable"}
        ]
        self.assertGreaterEqual(len(runnable), 1)

        for row in runnable:
            self.assertIsInstance(row["run_queue_rank"], int)

        ranks = sorted(int(row["run_queue_rank"]) for row in runnable)
        self.assertEqual(ranks, list(range(len(runnable))))

        active_row = next((row for row in runnable if row["is_active"]), None)
        if active_row is not None:
            self.assertEqual(active_row["run_queue_rank"], 0)

    def test_facade_can_delete_life_area(self) -> None:
        area = self.facade.create_life_area(name="Errands")
        self.facade.create_task(
            life_area_id=int(area["id"]),
            title="Buy groceries",
            urgency_tier="normal",
        )

        result = self.facade.delete_life_area(life_area_id=int(area["id"]))

        self.assertEqual(result["deleted_task_count"], 1)
        self.assertEqual(len(self.facade.list_life_areas()), 0)
        self.assertEqual(len(self.facade.list_tasks()), 0)

    def test_facade_can_rename_life_area(self) -> None:
        area = self.facade.create_life_area(name="Fitness")

        renamed = self.facade.rename_life_area(
            life_area_id=int(area["id"]),
            name="Health",
        )

        self.assertEqual(renamed["name"], "Health")
        all_areas = self.facade.list_life_areas()
        self.assertEqual(len(all_areas), 1)
        self.assertEqual(all_areas[0]["name"], "Health")

    def test_facade_can_reset_simulation(self) -> None:
        area = self.facade.create_life_area(name="Deep Work")
        self.facade.create_task(
            life_area_id=int(area["id"]),
            title="Draft architecture brief",
            urgency_tier="important",
        )
        self.assertIsNotNone(self.facade.what_next())

        reset = self.facade.reset_simulation()

        self.assertEqual(reset["status"], "ok")
        self.assertEqual(reset["reset_task_count"], 1)
        self.assertIsNone(self.facade.current_dispatch())

    def test_facade_can_delete_task(self) -> None:
        area = self.facade.create_life_area(name="Admin")
        task = self.facade.create_task(
            life_area_id=int(area["id"]),
            title="Close sprint board",
            urgency_tier="normal",
        )

        deleted = self.facade.delete_task(task_id=int(task["id"]))

        self.assertEqual(deleted["id"], task["id"])
        self.assertEqual(len(self.facade.list_tasks()), 0)

    def test_facade_can_update_task_active_window(self) -> None:
        area = self.facade.create_life_area(name="Health")
        task = self.facade.create_task(
            life_area_id=int(area["id"]),
            title="Sleep",
            urgency_tier="critical",
        )

        updated = self.facade.set_task_active_window(
            task_id=int(task["id"]),
            active_window_start_local="21:00",
            active_window_end_local="04:00",
        )
        self.assertEqual(updated["active_window_start_local"], "21:00")
        self.assertEqual(updated["active_window_end_local"], "04:00")

        cleared = self.facade.set_task_active_window(
            task_id=int(task["id"]),
            active_window_start_local=None,
            active_window_end_local=None,
        )
        self.assertIsNone(cleared["active_window_start_local"])
        self.assertIsNone(cleared["active_window_end_local"])

    def test_facade_can_change_task_urgency(self) -> None:
        area = self.facade.create_life_area(name="Admin")
        task = self.facade.create_task(
            life_area_id=int(area["id"]),
            title="Process invoices",
            urgency_tier="normal",
        )

        updated = self.facade.change_task_urgency(
            task_id=int(task["id"]),
            urgency_tier="important",
        )
        self.assertEqual(updated["urgency_tier"], "important")

        all_tasks = self.facade.list_tasks()
        self.assertEqual(len(all_tasks), 1)
        self.assertEqual(all_tasks[0]["urgency_tier"], "important")

    def test_facade_life_area_payload_omits_description(self) -> None:
        area = self.facade.create_life_area(name="Focus")

        self.assertNotIn("description", area)
        all_areas = self.facade.list_life_areas()
        self.assertEqual(len(all_areas), 1)
        self.assertNotIn("description", all_areas[0])

    def test_gui_host_uses_persisted_data_before_seed_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = GuiConfig(
                adapter_name="nextjs",
                frontend_dev=False,
                enable_timers=False,
                seed_scenario="workday_blend",
                data_dir=temp_dir,
            )

            host_a = GuiHost(config)
            try:
                first_task_count = len(host_a.scheduler.list_tasks())
                self.assertGreater(first_task_count, 0)
            finally:
                host_a.stop()

            host_b = GuiHost(config)
            try:
                second_task_count = len(host_b.scheduler.list_tasks())
                self.assertEqual(second_task_count, first_task_count)
            finally:
                host_b.stop()


if __name__ == "__main__":
    unittest.main()
