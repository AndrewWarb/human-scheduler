"""Terminal GUI adapter for simple interactive operation."""

from __future__ import annotations

import json

from human_sched.gui.contract import GuiAdapterMetadata
from human_sched.gui.facade import SchedulerGuiFacade


class TerminalGuiAdapter:
    """Minimal terminal adapter used as a second pluggable GUI."""

    metadata = GuiAdapterMetadata(
        name="terminal",
        version="1.0.0",
        capabilities=(
            "commands",
            "lifecycle",
        ),
    )

    __slots__ = ("_facade", "_running")

    def __init__(self, facade: SchedulerGuiFacade) -> None:
        self._facade = facade
        self._running = False

    def start(self) -> None:
        self._running = True
        print("Terminal GUI adapter started.")
        print("Commands: help, areas, tasks, what, pause <id>, resume <id>, complete <id>, quit")

        while self._running:
            try:
                raw = input("scheduler> ").strip()
            except EOFError:
                break
            except KeyboardInterrupt:
                break

            if not raw:
                continue

            if raw in {"quit", "exit"}:
                break
            if raw == "help":
                print("areas | tasks | what | pause <id> | resume <id> | complete <id> | quit")
                continue

            try:
                if raw == "areas":
                    print(json.dumps(self._facade.list_life_areas(), indent=2))
                elif raw == "tasks":
                    print(json.dumps(self._facade.list_tasks(), indent=2))
                elif raw == "what":
                    print(json.dumps(self._facade.what_next(), indent=2))
                elif raw.startswith("pause "):
                    task_id = int(raw.split(" ", 1)[1])
                    print(json.dumps(self._facade.pause_task(task_id=task_id), indent=2))
                elif raw.startswith("resume "):
                    task_id = int(raw.split(" ", 1)[1])
                    print(json.dumps(self._facade.resume_task(task_id=task_id), indent=2))
                elif raw.startswith("complete "):
                    task_id = int(raw.split(" ", 1)[1])
                    print(json.dumps(self._facade.complete_task(task_id=task_id), indent=2))
                else:
                    print("Unknown command. Type 'help'.")
            except Exception as exc:  # pragma: no cover - interactive adapter safety net
                print(f"Error: {exc}")

        self.stop()

    def stop(self) -> None:
        self._running = False
