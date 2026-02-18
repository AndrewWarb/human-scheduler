"""GUI host runtime that wires scheduler core to one selected GUI adapter."""

from __future__ import annotations

from human_sched.application.runtime import HumanTaskScheduler
from human_sched.gui.adapters import create_adapter
from human_sched.gui.config import GuiConfig
from human_sched.gui.events import EventHub
from human_sched.gui.facade import SchedulerGuiFacade
from human_sched.gui.notifier import EventingNotifier
from human_sched.gui.scenarios import apply_seed_scenario, available_seed_scenarios


class GuiHost:
    """Bootstraps scheduler runtime, facade, and one GUI adapter."""

    __slots__ = (
        "config",
        "event_hub",
        "notifier",
        "scheduler",
        "facade",
        "adapter",
    )

    def __init__(self, config: GuiConfig) -> None:
        self.config = config
        self.event_hub = EventHub()
        self.notifier = EventingNotifier(self.event_hub)
        self.scheduler = HumanTaskScheduler(
            env_file=config.env_file,
            notifier=self.notifier,
            enable_timers=config.enable_timers,
            persistence_dir=config.data_dir,
        )
        self.facade = SchedulerGuiFacade(scheduler=self.scheduler, event_hub=self.event_hub)
        try:
            has_persisted_state = bool(self.scheduler.list_life_areas() or self.scheduler.list_tasks())
            if has_persisted_state:
                self.facade.publish_info(f"Loaded persisted scheduler data from '{config.data_dir}'.")
            else:
                try:
                    apply_seed_scenario(self.facade, config.seed_scenario)
                except KeyError as exc:
                    options = ", ".join(item["key"] for item in available_seed_scenarios())
                    raise ValueError(
                        f"Unknown GUI_SCENARIO={config.seed_scenario!r}. Supported scenarios: {options}"
                    ) from exc

            self.adapter = create_adapter(
                config.adapter_name,
                facade=self.facade,
                config=config,
            )
        except Exception:
            self.scheduler.close()
            raise

    def start(self) -> None:
        self.adapter.start()

    def stop(self) -> None:
        try:
            self.adapter.stop()
        finally:
            self.scheduler.close()
