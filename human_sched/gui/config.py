"""Configuration loading for GUI host and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_TRUE_VALUES = {"1", "true", "yes", "on", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "n"}


@dataclass(frozen=True, slots=True)
class GuiConfig:
    """Runtime configuration for selecting and booting a GUI adapter."""

    adapter_name: str = "nextjs"
    host: str = "127.0.0.1"
    port: int = 8765
    frontend_dev: bool = True
    frontend_port: int = 3000
    data_dir: str = ".gui_data"
    env_file: str = ".env"
    seed_scenario: str = "workday_blend"
    open_browser: bool = False
    enable_timers: bool = True

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def load_gui_config(env_file: str = ".env") -> GuiConfig:
    """Load GUI config from env file with safe parsing defaults."""

    env = _parse_env_file(env_file)

    adapter_name = env.get("GUI_ADAPTER", "nextjs").strip() or "nextjs"
    host = env.get("GUI_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = _env_int(env, "GUI_PORT", default=8765, minimum=1)
    frontend_dev = _env_bool(env, "GUI_FRONTEND_DEV", default=True)
    frontend_port = _env_int(env, "GUI_FRONTEND_PORT", default=3000, minimum=1)
    data_dir = env.get("GUI_DATA_DIR", ".gui_data").strip() or ".gui_data"
    seed_scenario = env.get("GUI_SCENARIO", "workday_blend").strip() or "workday_blend"
    open_browser = _env_bool(env, "GUI_OPEN_BROWSER", default=False)
    enable_timers = _env_bool(env, "GUI_ENABLE_TIMERS", default=True)

    return GuiConfig(
        adapter_name=adapter_name,
        host=host,
        port=port,
        frontend_dev=frontend_dev,
        frontend_port=frontend_port,
        data_dir=data_dir,
        env_file=env_file,
        seed_scenario=seed_scenario,
        open_browser=open_browser,
        enable_timers=enable_timers,
    )


def _parse_env_file(path: str) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}

    env: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text[7:].strip()
        if "=" not in text:
            continue

        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        if key:
            env[key] = value

    return env


def _env_int(env: dict[str, str], key: str, default: int, minimum: int) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    if parsed < minimum:
        return default
    return parsed


def _env_bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or raw == "":
        return default

    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default
