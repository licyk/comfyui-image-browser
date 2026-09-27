"""Transfer Hanaikada events to ComfyUI's event loop."""

import asyncio
from collections.abc import Callable
from typing import Any

EVENT_NAME = "comfyui-image-browser.inputs-changed"


def subscribe_changes(services: Any, root_id: str, loop: asyncio.AbstractEventLoop, notify: Callable[[], None]) -> Callable[[], None]:
    """Debounce file operations in one root; never touch ComfyUI from Hanaikada's threads.

    ``library_changed`` is published by uploads, moves, copies, renames and deletes made through
    the browser. Scanner events are left out: they report files ComfyUI itself already knows.
    """
    timer: asyncio.TimerHandle | None = None
    active = True

    def flush() -> None:
        nonlocal timer
        timer = None
        if active:
            notify()

    def schedule() -> None:
        nonlocal timer
        if active and timer is None:
            timer = loop.call_later(0.4, flush)

    def handler(event: Any) -> None:
        if active and event.__event_name__ == "library_changed" and getattr(event, "root_id", None) == root_id:
            try:
                loop.call_soon_threadsafe(schedule)
            except RuntimeError:
                pass  # The application event loop has already closed.

    unsubscribe = services.events.subscribe(handler)

    def close() -> None:
        nonlocal active
        active = False
        unsubscribe()
        if timer is not None:
            timer.cancel()

    return close
