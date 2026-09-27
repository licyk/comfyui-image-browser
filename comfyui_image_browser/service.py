"""Own a lazily started Hanaikada server without blocking ComfyUI's event loop."""

import asyncio
import logging
import secrets
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .events import subscribe_changes
from .image_roots import INPUT, OUTPUT, ROOT_IDS, TEMP, RootSpec

logger = logging.getLogger("Image-Browser")
BROWSER_PREFIX = "/image-browser"
ROOT_NAMES = {OUTPUT: "output", INPUT: "input", TEMP: "temp"}


class BrowserService:
    def __init__(
        self,
        data_dir: Path,
        roots: Callable[[], list[RootSpec]],
        notify: Callable[[], None],
        public_base_url: str | None = None,
        factory: Callable[..., Any] | None = None,
        combined_view: bool = True,
    ) -> None:
        self.data_dir = data_dir
        self.roots = roots
        self.notify = notify
        self.public_base_url = public_base_url
        self.combined_view = combined_view
        self.token = secrets.token_urlsafe(32)
        self._factory = factory
        self._server: Any = None
        self._starting: asyncio.Task[None] | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._closing = False
        self.state = "stopped"
        self.error: str | None = None

    @property
    def upstream(self) -> str:
        if self._server is None or not self._server.running:
            raise RuntimeError("Hanaikada is not running")
        return self._server.url

    def status(self) -> dict[str, Any]:
        state = self.state
        if state == "ready" and (self._server is None or not self._server.running):
            state = "failed"
        return {"state": state, "error": self.error if state != "ready" else None}

    async def ensure_started(self) -> None:
        if self._closing:
            raise RuntimeError("Hanaikada is shutting down")
        if self.status()["state"] == "ready":
            return
        if self._starting is None or self._starting.done():
            self._starting = asyncio.create_task(self._start())
            # Observe errors even if the browser disconnects during startup.
            self._starting.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        await asyncio.shield(self._starting)

    async def _start(self) -> None:
        self.state, self.error = "starting", None
        try:
            if self._unsubscribe:
                self._unsubscribe()
                self._unsubscribe = None
            roots = await asyncio.to_thread(self.roots)
            await asyncio.to_thread(self._start_sync, roots)
            self._unsubscribe = subscribe_changes(self._server.services, ROOT_IDS[INPUT], asyncio.get_running_loop(), self.notify)
            self.state = "ready"
        except Exception as exc:
            self.state, self.error = "failed", str(exc)
            logger.exception("Could not start Hanaikada")
            raise

    def _start_sync(self, roots: list[RootSpec]) -> None:
        from hanaikada import HanaikadaServer, ImageRoot
        from hanaikada.api.static import web_dist_dir

        if self._server is not None:
            self._server.stop()
            self._server = None
        if not (web_dist_dir() / "index.html").is_file():
            raise RuntimeError("Hanaikada's web UI is missing. Install its release wheel, or build its web UI first.")
        self._server = (self._factory or HanaikadaServer)(
            data_dir=self.data_dir,
            image_roots=[ImageRoot(root.path, layout="custom", name=ROOT_NAMES[root.kind], id=root.id, index=root.index) for root in roots],
            # The folders are ComfyUI's; adding one would expose any server path to the browser.
            lock_image_roots=True,
            host="127.0.0.1",
            port=0,
            open_browser=False,
            access_token=self.token,
            api_prefix=BROWSER_PREFIX,
            public_base_url=self.public_base_url,
            # Pinned: output and input side by side, so Browse opens on "All folders".
            settings={"server": {"allowed_origins": []}, "library": {"combined_view": self.combined_view}},
        )
        try:
            self._server.start()
        except BaseException:
            self._server.stop()
            self._server = None
            raise

    async def scan(self, folders: Iterable[tuple[str, str]]) -> int:
        """Queue (root id, relative folder) scans so a new output appears without waiting for the watcher.

        Never starts the server: before the browser is opened, its start-up scan finds the files.
        """
        services = getattr(self._server, "services", None)
        if self.status()["state"] != "ready" or services is None:
            return 0
        from hanaikada.core.errors import HanaikadaError
        from hanaikada.core.index.models import ScanRequest

        requests = list(folders)

        def submit() -> int:
            queued = 0
            for root_id, path in requests:
                try:
                    services.index.request_scan(ScanRequest(root_id=root_id, path=path))
                    queued += 1
                except HanaikadaError as exc:
                    # An unknown root, a missing folder or a path outside the root: nothing to scan.
                    logger.debug("Skipping scan of %s:%s: %s", root_id, path, exc)
            return queued

        return await asyncio.to_thread(submit)

    async def close(self) -> None:
        self._closing = True
        if self._starting is not None:
            try:
                await asyncio.shield(self._starting)
            except Exception:
                pass
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        await asyncio.to_thread(self.stop_at_exit)
        self.state = "stopped"

    def stop_at_exit(self) -> None:
        """ComfyUI's direct CLI shutdown does not currently clean up its aiohttp runner."""
        server, self._server = self._server, None
        if server is not None:
            server.stop()
