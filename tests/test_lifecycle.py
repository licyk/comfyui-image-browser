import asyncio
import threading

import pytest
from hanaikada import HanaikadaServer


async def test_failed_start_can_be_retried(browser):
    service, _, client, _, _ = browser

    def fail(**_options):
        raise RuntimeError("Test startup failure")

    service._factory = fail
    response = await client.post("/image-browser-extension/start")
    assert response.status == 503
    assert (await response.json())["error"] == "Test startup failure"
    service._factory = None
    response = await client.post("/image-browser-extension/start")
    assert response.status == 200
    assert service.status()["state"] == "ready"


async def test_disconnected_start_request_and_shutdown_leave_no_server(browser):
    service, _, _, _, _ = browser
    entered = threading.Event()
    proceed = threading.Event()
    instances = []

    def delayed(**options):
        entered.set()
        assert proceed.wait(5)
        instance = HanaikadaServer(**options)
        instances.append(instance)
        return instance

    service._factory = delayed
    request = asyncio.create_task(service.ensure_started())
    assert await asyncio.to_thread(entered.wait, 5)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    close = asyncio.create_task(service.close())
    proceed.set()
    await asyncio.wait_for(close, 10)
    assert len(instances) == 1
    assert not instances[0].running
    assert service.state == "stopped"


async def test_scan_is_ignored_after_shutdown(browser):
    service, _, client, _, _ = browser
    await client.post("/image-browser-extension/start")
    await service.close()
    assert await service.scan([("comfyui-output", "")]) == 0
