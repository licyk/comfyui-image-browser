import asyncio
import re

import pytest
import socketio
from aiohttp import ClientSession

from tests.helpers import PROMPT, comfy_png


async def start(client):
    response = await client.post("/image-browser-extension/start")
    assert response.status == 200, await response.text()
    assert (await response.json())["state"] == "ready"


def same_origin(client) -> dict[str, str]:
    return {"Origin": str(client.make_url("/")).rstrip("/")}


async def wait_for(condition, timeout: float = 10.0):
    for _ in range(int(timeout / 0.1)):
        result = await condition()
        if result:
            return result
        await asyncio.sleep(0.1)
    raise AssertionError("condition not met in time")


async def test_start_is_singleton_and_private_port_requires_token(browser):
    service, _, client, _, _ = browser
    assert (await (await client.get("/image-browser-extension/status")).json())["state"] == "stopped"
    await asyncio.gather(*(start(client) for _ in range(4)))
    url = service.upstream
    await start(client)
    assert service.upstream == url
    async with ClientSession() as direct:
        response = await direct.get(url + "/api/v1/library/roots")
        assert response.status == 401
    response = await client.get("/image-browser/api/v1/library/roots")
    assert response.status == 200
    roots = await response.json()
    assert [(root["id"], root["name"], root["layout"]) for root in roots] == [
        ("comfyui-output", "output", "custom"),
        ("comfyui-input", "input", "custom"),
    ]
    await service.close()
    assert service.status()["state"] == "stopped"


async def test_comfyui_folders_are_locked(browser):
    service, _, client, (output, _), _ = browser
    await start(client)
    meta = await (await client.get("/image-browser/api/v1/app/meta")).json()
    assert meta["roots_locked"] is True
    for method, path, body in [
        ("POST", "/image-browser/api/v1/library/roots", {"path": "/", "layout": "custom"}),
        ("PATCH", "/image-browser/api/v1/library/roots/comfyui-output", {"path": "/"}),
        ("DELETE", "/image-browser/api/v1/library/roots/comfyui-input", None),
    ]:
        response = await client.request(method, path, json=body, headers=same_origin(client))
        assert response.status == 409, await response.text()
    roots = await (await client.get("/image-browser/api/v1/library/roots")).json()
    assert roots[0]["path"] == str(output)


async def test_ui_assets_and_prefixed_alias(browser):
    _, _, client, _, _ = browser
    await start(client)
    response = await client.get("/image-browser", allow_redirects=False)
    assert response.status == 307 and response.headers["Location"] == "/image-browser/"
    response = await client.get("/image-browser/", headers={"Accept": "text/html"})
    html = await response.text()
    assert response.status == 200 and 'id="app"' in html
    asset = re.search(r'src="(\./assets/[^"]+\.js)"', html).group(1)
    response = await client.get("/image-browser/" + asset.removeprefix("./"))
    assert response.status == 200 and "javascript" in response.headers["Content-Type"]
    response = await client.get("/api/image-browser/api/v1/app/health")
    assert response.status == 200


async def test_generated_image_is_indexed_with_its_comfyui_metadata(browser):
    service, _, client, (output, _), _ = browser
    comfy_png(output / "2026-09-27" / "ComfyUI_00001_.png")
    await start(client)
    listing = await (await client.get("/image-browser/api/v1/library/roots/comfyui-output/entries")).json()
    assert [folder["name"] for folder in listing["folders"]] == ["2026-09-27"]

    async def detail():
        response = await client.get(
            "/image-browser/api/v1/images/by-path", params={"root_id": "comfyui-output", "path": "2026-09-27/ComfyUI_00001_.png"}
        )
        return await response.json() if response.status == 200 else None

    image = await wait_for(detail)
    assert image["record"]["platform"] == "comfyui"
    assert image["prompt"] == PROMPT
    response = await client.get(
        "/image-browser/api/v1/library/roots/comfyui-output/thumbnail", params={"path": "2026-09-27/ComfyUI_00001_.png", "size": 128}
    )
    assert response.status == 200 and response.headers["Content-Type"] == "image/webp"


async def test_scan_endpoint_indexes_new_results_and_ignores_a_stopped_browser(browser):
    service, _, client, (output, _), _ = browser
    body = {"items": [{"type": "output", "subfolder": "batch"}, {"type": "output", "subfolder": "../escape"}, {"type": "temp"}]}
    response = await client.post("/image-browser-extension/scan", json=body)
    assert response.status == 200 and (await response.json())["queued"] == 0
    assert service.state == "stopped"
    await start(client)
    assert service._server.services.index.wait_idle(20)
    comfy_png(output / "batch" / "ComfyUI_00002_.png", text="a new result")
    response = await client.post("/image-browser-extension/scan", json=body)
    assert (await response.json())["queued"] == 1

    async def found():
        response = await client.post("/image-browser/api/v1/search", json={"text": "a new result"}, headers=same_origin(client))
        page = await response.json()
        return page["items"] if response.status == 200 and page["items"] else None

    items = await wait_for(found)
    assert items[0]["path"] == "batch/ComfyUI_00002_.png"
    response = await client.post("/image-browser-extension/scan", json=body, headers={"Origin": "https://evil.example"})
    assert response.status == 403


async def test_moving_into_input_notifies_comfyui_but_output_changes_do_not(browser):
    _, _, client, (output, input), notifications = browser
    comfy_png(output / "ComfyUI_00003_.png")
    await start(client)
    response = await client.post(
        "/image-browser/api/v1/library/folders", json={"root_id": "comfyui-output", "name": "kept"}, headers=same_origin(client)
    )
    assert response.status == 201, await response.text()
    await asyncio.sleep(0.6)
    assert notifications == []
    response = await client.post(
        "/image-browser/api/v1/library/copy",
        json={"items": [{"root_id": "comfyui-output", "path": "ComfyUI_00003_.png"}], "dest_root_id": "comfyui-input"},
        headers=same_origin(client),
    )
    assert response.status == 200, await response.text()
    assert (input / "ComfyUI_00003_.png").is_file()
    await asyncio.sleep(0.6)
    assert notifications == [True]


async def test_streamed_upload_to_input_and_unicode_names(browser):
    _, _, client, (_, input), notifications = browser
    await start(client)
    content = comfy_png(input.parent / "source.png").read_bytes()

    async def body():
        for index in range(0, len(content), 64):
            yield content[index : index + 64]

    response = await client.put(
        "/image-browser/api/v1/library/upload",
        params={"root_id": "comfyui-input", "name": "参考图 #1.png"},
        data=body(),
        headers=same_origin(client),
    )
    assert response.status == 201, await response.text()
    assert (input / "参考图 #1.png").read_bytes() == content
    await asyncio.sleep(0.6)
    assert notifications
    response = await client.get("/image-browser/api/v1/library/roots/comfyui-input/file", params={"path": "参考图 #1.png"})
    assert response.status == 200 and await response.read() == content


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": "http://["},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
async def test_cross_origin_start_cannot_launch_service(browser, headers):
    service, _, client, _, _ = browser
    response = await client.post("/image-browser-extension/start", headers=headers)
    assert response.status == 403
    assert response.content_type == "application/json"
    assert (await response.json())["error"]
    assert service.state == "stopped"


@pytest.mark.parametrize("transport", ["websocket", "polling"])
async def test_socketio_events_through_both_transports(browser, transport):
    service, _, client, _, _ = browser
    await start(client)
    socket = socketio.AsyncClient()
    arrived = asyncio.Event()
    socket.on("library_changed", lambda _event: arrived.set())
    try:
        await socket.connect(str(client.make_url("/")), socketio_path="image-browser/ws/socket.io", transports=[transport])
        service._server.services.library.notify_changed("comfyui-output", "")
        await asyncio.wait_for(arrived.wait(), 5)
    finally:
        await socket.disconnect()


async def test_all_folders_is_pinned_on_and_lists_output_then_input(browser):
    _, _, client, (output, input), _ = browser
    comfy_png(output / "day" / "ComfyUI_00004_.png")
    await start(client)
    settings = await (await client.get("/image-browser/api/v1/settings")).json()
    assert settings["library"]["combined_view"] is True
    response = await client.patch("/image-browser/api/v1/settings", json={"library": {"combined_view": False}}, headers=same_origin(client))
    assert (await response.json())["library"]["combined_view"] is True
    listing = await (await client.get("/image-browser/api/v1/library/combined/entries")).json()
    # Each folder is its own root, so it appears once, named after ComfyUI's folder.
    assert [(f["root_id"], f["display_name"], f["path"], f["is_root"]) for f in listing["folders"]] == [
        ("comfyui-output", "output", "", True),
        ("comfyui-input", "input", "", True),
    ]
    assert listing["missing_roots"] == []


async def test_all_folders_can_be_pinned_off(browser):
    service, _, client, _, _ = browser
    service.combined_view = False
    await start(client)
    settings = await (await client.get("/image-browser/api/v1/settings")).json()
    assert settings["library"]["combined_view"] is False
    response = await client.patch("/image-browser/api/v1/settings", json={"library": {"combined_view": True}}, headers=same_origin(client))
    assert (await response.json())["library"]["combined_view"] is False
