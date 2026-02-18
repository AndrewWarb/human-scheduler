"""Adapter registry for GUI host runtime selection."""

from __future__ import annotations

from human_sched.gui.config import GuiConfig
from human_sched.gui.facade import SchedulerGuiFacade

from .nextjs import NextJsGuiAdapter
from .terminal import TerminalGuiAdapter


def available_adapters() -> tuple[str, ...]:
    return ("nextjs", "terminal")


def create_adapter(name: str, *, facade: SchedulerGuiFacade, config: GuiConfig):
    normalized = name.strip().lower()

    if normalized == "nextjs":
        return NextJsGuiAdapter(
            facade=facade,
            host=config.host,
            port=config.port,
            frontend_dev=config.frontend_dev,
            frontend_port=config.frontend_port,
            open_browser=config.open_browser,
        )
    if normalized == "terminal":
        return TerminalGuiAdapter(facade=facade)

    options = ", ".join(available_adapters())
    raise ValueError(f"Unknown GUI_ADAPTER={name!r}. Supported adapters: {options}")
