"""Web GUI adapter (named `nextjs`) using HTTP/JSON + SSE transport."""

from __future__ import annotations

import os
from pathlib import Path
from subprocess import Popen, TimeoutExpired
import time
from urllib.request import urlopen
import webbrowser

from human_sched.gui.contract import GuiAdapterMetadata
from human_sched.gui.facade import SchedulerGuiFacade
from human_sched.gui.http_service import SchedulerHttpService


class NextJsGuiAdapter:
    """Launches the web GUI transport and serves the frontend assets."""

    metadata = GuiAdapterMetadata(
        name="nextjs",
        version="1.0.0",
        capabilities=(
            "http_json",
            "sse",
            "dashboard",
            "tasks",
            "life_areas",
            "activity",
            "settings",
        ),
    )

    __slots__ = (
        "_service",
        "_open_browser",
        "_frontend_dev",
        "_frontend_port",
        "_frontend_bind_host",
        "_frontend_browser_host",
        "_frontend_url",
        "_frontend_process",
        "_nextjs_site_dir",
    )

    def __init__(
        self,
        *,
        facade: SchedulerGuiFacade,
        host: str,
        port: int,
        frontend_dev: bool,
        frontend_port: int,
        open_browser: bool,
    ) -> None:
        nextjs_site_dir = Path(__file__).resolve().parent.parent / "nextjs_site"
        static_dir = nextjs_site_dir / "out"
        self._service = SchedulerHttpService(
            facade=facade,
            metadata=self.metadata,
            host=host,
            port=port,
            static_dir=static_dir,
        )
        self._open_browser = open_browser
        self._frontend_dev = frontend_dev
        self._frontend_port = frontend_port
        self._frontend_bind_host = host
        self._frontend_browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        self._frontend_url = f"http://{self._frontend_browser_host}:{frontend_port}"
        self._frontend_process: Popen[bytes] | None = None
        self._nextjs_site_dir = nextjs_site_dir

    @property
    def base_url(self) -> str:
        return self._service.base_url

    def start(self) -> None:
        if self._frontend_dev:
            self._start_frontend_dev()
            print(
                "Starting Next.js GUI adapter "
                f"(API: {self.base_url}, Frontend dev: {self._frontend_url})"
            )
        else:
            print(f"Starting Next.js GUI adapter at {self.base_url}")

        if self._open_browser:
            target = self._frontend_url if self._frontend_dev else self.base_url
            webbrowser.open(target)
        self._service.serve_forever()

    def stop(self) -> None:
        self._service.stop()
        process = self._frontend_process
        self._frontend_process = None
        if process is None:
            return
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=6)
        except TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def _start_frontend_dev(self) -> None:
        if self._frontend_process is not None:
            return

        command = [
            "npm",
            "run",
            "dev",
            "--",
            "--hostname",
            self._frontend_bind_host,
            "--port",
            str(self._frontend_port),
        ]
        env = os.environ.copy()
        env.setdefault("NEXT_PUBLIC_API_URL", "")

        try:
            self._frontend_process = Popen(
                command,
                cwd=self._nextjs_site_dir,
                env=env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Failed to start Next.js dev server: npm command not found."
            ) from exc

        self._wait_for_frontend_ready()

    def _wait_for_frontend_ready(self) -> None:
        process = self._frontend_process
        if process is None:
            return

        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                code = process.returncode
                raise RuntimeError(f"Next.js dev server exited with code {code}.")
            try:
                with urlopen(self._frontend_url, timeout=1.0):
                    return
            except Exception:
                time.sleep(0.25)

        print(
            "Next.js dev server is still starting; "
            "first page load may take a few extra seconds."
        )
