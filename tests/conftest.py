"""Exercise the released Hanaikada behind a real aiohttp server with temporary ComfyUI folders."""

import sys
from pathlib import Path

import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comfyui_image_browser.image_roots import collect_image_roots
from comfyui_image_browser.proxy import BrowserProxy
from comfyui_image_browser.service import BrowserService
from tests.helpers import comfy_dirs


def add_routes(app: web.Application, proxy: BrowserProxy, prefix: str = "") -> None:
    app.router.add_get(prefix + "/image-browser-extension/status", proxy.status)
    app.router.add_post(prefix + "/image-browser-extension/start", proxy.start)
    app.router.add_post(prefix + "/image-browser-extension/scan", proxy.scan)
    app.router.add_get(prefix + "/image-browser-extension/open", proxy.open_page)
    app.router.add_get(prefix + "/image-browser-extension/open.js", proxy.open_script)
    app.router.add_get(prefix + "/image-browser", proxy.handle)
    app.router.add_route("*", prefix + "/image-browser/{tail:.*}", proxy.handle)


@pytest_asyncio.fixture
async def browser(tmp_path):
    output, input, _ = comfy_dirs(tmp_path)
    notifications = []
    service = BrowserService(tmp_path / "data", lambda: collect_image_roots(output, input), lambda: notifications.append(True))
    proxy = BrowserProxy(service)
    app = web.Application(client_max_size=2 * 1024 * 1024)
    add_routes(app, proxy)
    # ComfyUI also publishes every extension route under /api.
    add_routes(app, proxy, "/api")
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield service, proxy, client, (output, input), notifications
    finally:
        await proxy.close()
        await service.close()
        await client.close()
