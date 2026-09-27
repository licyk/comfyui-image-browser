"""Real Chromium + released Hanaikada UI, with a small Comfy extension API harness.

The harness exercises the extension's public registration contract; it is not a full
ComfyUI frontend or a GPU workflow test.
"""

import os
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect

from comfyui_image_browser.image_roots import collect_image_roots
from comfyui_image_browser.proxy import BrowserProxy
from comfyui_image_browser.service import BrowserService
from tests.conftest import add_routes
from tests.helpers import comfy_dirs, comfy_png

API_JS = """
export const api = new EventTarget();
api.fileURL = path => '/comfy' + path;
api.apiURL = path => '/comfy/api' + path;
api.fetchApi = (path, options) => fetch('/comfy/api' + path, options);
window.browserTestApi = api;
"""
APP_JS = """
window.browserTestRefreshes = 0;
// Enough of the canvas and LiteGraph for "Send to Load Image", and a record of handled files.
window.browserTestFiles = [];
window.browserTestNodes = [];
window.LiteGraph = {createNode: type => ({
    type, comfyClass: type, pos: [0, 0], setDirtyCanvas() {},
    widgets: [{name: 'image', value: '', options: {values: []}, callback(value) { this.preview = value; }}],
})};
const settings = document.createElement('div');
document.body.append(settings);
export const app = {
    menu: {settingsGroup: {element: settings}},
    canvas: {
        selected_nodes: {},
        graph: {add: node => { window.browserTestNodes.push(node); return node; }},
        selectNode(node) { this.selected_nodes = {[window.browserTestNodes.indexOf(node)]: node}; },
        ds: {convertCanvasToOffset: ([x, y]) => [x, y]},
        canvas: {clientWidth: 800, clientHeight: 600},
    },
    async handleFile(file) { window.browserTestFiles.push({name: file.name, type: file.type, size: file.size}); },
    extensionManager: {
        setting: {get: () => 'en'},
        command: {execute: async () => {window.browserTestRefreshes++;}},
    },
    async registerExtension(extension) {
        window.browserTestApp = app;
        window.browserExtension = extension;
        await extension.setup?.();
        for (const action of extension.actionBarButtons || []) {
            const button = document.createElement('button');
            button.textContent = action.label || '';
            button.setAttribute('aria-label', action.tooltip);
            button.onclick = action.onClick;
            document.body.append(button);
        }
    },
};
"""
BUTTON_JS = """
export class ComfyButton {
    constructor({action, tooltip, content, classList}) {
        this.element = document.createElement('button');
        this.element.append(content);
        this.element.title = tooltip;
        this.element.className = classList;
        this.element.onclick = action;
    }
}
"""
GROUP_JS = """
export class ComfyButtonGroup {
    constructor(...buttons) {
        this.element = document.createElement('div');
        this.element.append(...buttons);
    }
}
"""


UPLOADS = web.AppKey("uploads", list)


def script(body: str):
    async def handler(_):
        return web.Response(text=body, content_type="text/javascript")

    return handler


def harness(
    service: BrowserService, proxy: BrowserProxy, frontend_version: str | None = None, input_dir: Path | None = None
) -> tuple[web.Application, list[str]]:
    """A page loading the extension like ComfyUI does; records which legacy modules it imports."""
    app = web.Application()
    legacy_imports: list[str] = []
    app[UPLOADS] = []

    async def upload(request):
        # ComfyUI's /upload/image, reduced to what the extension sends: an image into input.
        form = await request.post()
        field = form["image"]
        assert form["type"] == "input" and input_dir is not None
        (input_dir / field.filename).write_bytes(field.file.read())
        request.app[UPLOADS].append(field.filename)
        return web.json_response({"name": field.filename, "subfolder": "", "type": "input"})

    app.router.add_post("/comfy/api/upload/image", upload)
    version = f"<script>window.__COMFYUI_FRONTEND_VERSION__ = {frontend_version!r};</script>" if frontend_version else ""

    async def page(_):
        return web.Response(
            text=f'<html><body>{version}<script type="module" src="/comfy/extensions/image-browser/image_browser.js"></script></body></html>',
            content_type="text/html",
        )

    def legacy(body: str):
        serve = script(body)

        async def handler(request):
            legacy_imports.append(request.path)
            return await serve(request)

        return handler

    app.router.add_get("/comfy/", page)
    app.router.add_get("/comfy/scripts/api.js", script(API_JS))
    app.router.add_get("/comfy/scripts/app.js", script(APP_JS))
    app.router.add_get("/comfy/scripts/ui/components/button.js", legacy(BUTTON_JS))
    app.router.add_get("/comfy/scripts/ui/components/buttonGroup.js", legacy(GROUP_JS))
    app.router.add_static("/comfy/extensions/image-browser/", Path(__file__).resolve().parents[1] / "js")
    add_routes(app, proxy, "/comfy")
    add_routes(app, proxy, "/comfy/api")
    return app, legacy_imports


async def launch(playwright):
    return await playwright.chromium.launch(
        headless=True, executable_path=os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE"), args=["--no-sandbox"]
    )


async def test_current_frontends_get_an_action_bar_button_without_legacy_imports(tmp_path):
    output, input, _ = comfy_dirs(tmp_path)
    service = BrowserService(tmp_path / "data", lambda: collect_image_roots(output, input), lambda: None)
    proxy = BrowserProxy(service)
    app, legacy_imports = harness(service, proxy, "1.53.6")
    async with TestServer(app) as server, async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            tab = await browser.new_page()
            await tab.goto(str(server.make_url("/comfy/")))
            button = tab.get_by_role("button", name="Image Browser", exact=True)
            await button.click()
            await expect(tab.frame_locator("iframe").get_by_role("navigation", name="Main")).to_be_visible(timeout=30000)
            assert await tab.evaluate("window.browserExtension.name") == "ComfyUI.ImageBrowser.Toolbar"
            assert legacy_imports == []
        finally:
            await browser.close()
            await proxy.close()
            await service.close()


async def test_button_iframe_results_close_reopen_retry_and_refresh(tmp_path):
    output, input, _ = comfy_dirs(tmp_path)
    comfy_png(output / "ComfyUI_00001_.png")
    service = BrowserService(tmp_path / "data", lambda: collect_image_roots(output, input), lambda: None)
    proxy = BrowserProxy(service)
    app, legacy_imports = harness(service, proxy)
    async with TestServer(app) as server, async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            tab = await browser.new_page()
            errors = []
            tab.on("pageerror", lambda error: errors.append(str(error)))
            await tab.goto(str(server.make_url("/comfy/")))
            button = tab.get_by_role("button", name="Image Browser", exact=True)
            await expect(button).to_have_text("")
            await expect(button.locator("i")).to_have_class("icon-[lucide--images] comfy-image-browser-icon")
            # Without a frontend version (older than the action bar API) the legacy toolbar is used.
            assert len(legacy_imports) == 2

            async def html_error(route):
                await route.fulfill(status=404, content_type="text/html", body="<html><body>Not found</body></html>")

            await tab.route("**/comfy/api/image-browser-extension/start", html_error)
            await button.click()
            await expect(tab.get_by_role("status")).to_contain_text("HTTP 404")
            await expect(tab.get_by_role("status")).to_contain_text("/comfy/api/image-browser-extension/start")
            await expect(tab.get_by_role("status")).to_contain_text("Restart ComfyUI")
            await expect(tab.locator("iframe")).to_be_hidden()
            await tab.unroute("**/comfy/api/image-browser-extension/start", html_error)
            assert service.state == "stopped"

            # The link bootstraps a fresh tab even though the dialog failed to start.
            async with tab.expect_popup() as popup_info:
                await tab.get_by_role("link", name="Open in new tab").click()
            popup = await popup_info.value
            await expect(popup.get_by_role("navigation", name="Main")).to_be_visible(timeout=30000)
            assert "/comfy/image-browser/#/browse" in popup.url
            assert await popup.evaluate("window.opener === null")
            await popup.close()

            # A deployment that refuses framing must be named instead of the generic failure.
            async def deny_framing(route):
                if route.request.resource_type != "document":
                    await route.continue_()
                    return
                await route.fulfill(
                    status=200,
                    content_type="text/html",
                    headers={"X-Frame-Options": "deny"},
                    body='<html><body><div id="app"></div></body></html>',
                )

            await tab.route("**/comfy/image-browser/**", deny_framing)
            await tab.get_by_role("button", name="Retry", exact=True).click()
            await expect(tab.get_by_role("status")).to_contain_text("X-Frame-Options")
            await expect(tab.locator("iframe")).to_be_hidden()
            await tab.unroute("**/comfy/image-browser/**", deny_framing)

            # A proxy adding only X-Frame-Options is overridden by the frame-ancestors policy.
            async def proxy_denies_framing(route):
                if route.request.resource_type != "document":
                    await route.continue_()
                    return
                response = await route.fetch()
                await route.fulfill(response=response, headers={**response.headers, "x-frame-options": "deny"})

            await tab.route("**/comfy/image-browser/**", proxy_denies_framing)
            await tab.get_by_role("button", name="Close", exact=True).click()
            await button.click()
            frame = tab.frame_locator("iframe")
            await expect(frame.get_by_role("navigation", name="Main")).to_be_visible(timeout=30000)
            await tab.unroute("**/comfy/image-browser/**", proxy_denies_framing)
            # A document fulfilled by Playwright has no network address, so Chromium's local network
            # checks would block its socket to 127.0.0.1; load it from the server itself.
            await frame.locator("body").evaluate("() => location.reload()")
            await expect(frame.get_by_role("navigation", name="Main")).to_be_visible(timeout=30000)
            # Pinned "All folders" opens first, with ComfyUI's folders side by side.
            await expect(frame.locator('[aria-current="location"]')).to_have_text("All folders")
            cells = frame.locator(".slot")
            await expect(cells).to_have_text(["output", "input"])
            await cells.filter(has_text="output").dblclick()
            await expect(frame.locator('[aria-current="location"]')).to_have_text("output")
            # Thumbnails load through the proxy, which alone holds the private token.
            images = frame.locator("img.loaded")
            await expect(images).to_have_count(1, timeout=30000)
            hub_src = await tab.locator("iframe").get_attribute("src")
            assert "/comfy/image-browser/" in hub_src and hub_src.endswith("#/browse")

            # A finished prompt's result shows up without waiting for the folder watcher.
            comfy_png(output / "ComfyUI_00002_.png", text="second", seed=7)
            await tab.evaluate(
                """window.browserTestApi.dispatchEvent(new CustomEvent('executed', {detail: {output: {images: [
                    {filename: 'ComfyUI_00002_.png', subfolder: '', type: 'output'},
                    {filename: 'preview.png', subfolder: '', type: 'temp'},
                ]}}}))"""
            )
            await expect(images).to_have_count(2, timeout=15000)
            if os.getenv("IMAGE_BROWSER_SCREENSHOT"):
                await tab.screenshot(path=os.environ["IMAGE_BROWSER_SCREENSHOT"])

            # Escape on the page itself closes the dialog; the iframe and its state are kept.
            await frame.locator("body").evaluate("el => el.dataset.sessionMarker = 'kept'")
            await tab.get_by_role("button", name="Maximize", exact=True).click()
            await expect(tab.get_by_role("button", name="Restore", exact=True)).to_be_visible()
            await frame.locator("body").evaluate("el => { document.activeElement?.blur(); }")
            await frame.locator("body").press("Escape")
            await expect(tab.locator("dialog.comfy-image-browser")).not_to_have_attribute("open", "")
            await expect(button).to_be_focused()
            await button.click()
            assert await frame.locator("body").get_attribute("data-session-marker") == "kept"
            assert await tab.locator("iframe").count() == 1

            await tab.evaluate(
                "for (let i=0;i<5;i++) window.browserTestApi.dispatchEvent(new CustomEvent('comfyui-image-browser.inputs-changed'))"
            )
            await tab.wait_for_function("window.browserTestRefreshes === 1")
            await tab.get_by_role("button", name="Close", exact=True).click()

            # A failed restart remains recoverable through the visible Retry action.
            await service.close()
            service._closing = False

            def failure(**_):
                raise RuntimeError("Test restart failure")

            service._factory = failure
            await button.click()
            await expect(tab.get_by_role("button", name="Retry", exact=True)).to_be_visible()
            service._factory = None
            await tab.get_by_role("button", name="Retry", exact=True).click()
            await expect(frame.get_by_role("navigation", name="Main")).to_be_visible(timeout=30000)
            await expect(frame.locator("img.loaded")).to_have_count(2, timeout=30000)
            assert errors == []
        finally:
            await browser.close()
            await proxy.close()
            await service.close()


async def test_send_to_comfyui_opens_workflows_and_fills_load_image(tmp_path):
    from PIL import Image

    output, input, _ = comfy_dirs(tmp_path)
    comfy_png(output / "ComfyUI_00001_.png")
    Image.new("RGB", (2, 2)).save(output / "plain.png")
    comfy_png(input / "mask.png")
    service = BrowserService(tmp_path / "data", lambda: collect_image_roots(output, input), lambda: None)
    proxy = BrowserProxy(service)
    app, _ = harness(service, proxy, "1.53.6", input_dir=input)
    async with TestServer(app) as server, async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            tab = await browser.new_page()
            errors = []
            tab.on("pageerror", lambda error: errors.append(str(error)))
            await tab.goto(str(server.make_url("/comfy/")))
            button = tab.get_by_role("button", name="Image Browser", exact=True)
            dialog = tab.locator("dialog.comfy-image-browser")
            frame = tab.frame_locator("iframe")
            menu = frame.locator('.menu[role="menu"]').last

            async def open_menu(folder: str, name: str):
                await button.click()
                await expect(frame.get_by_role("navigation", name="Main")).to_be_visible(timeout=30000)
                await frame.locator("body").evaluate("(el, f) => { location.hash = '#/browse?root=' + f; }", folder)
                cell = frame.locator(".slot").filter(has_text=name)
                await expect(cell).to_be_visible(timeout=15000)
                await cell.click(button="right")
                await expect(menu).to_be_visible()

            # A ComfyUI image offers both; a PNG without metadata only Load Image.
            await open_menu("comfyui-output", "plain.png")
            await expect(menu.get_by_text("Send to Load Image")).to_be_visible()
            await expect(menu.get_by_text("Open workflow")).to_have_count(0)
            await frame.locator("body").press("Escape")
            await frame.locator(".slot").filter(has_text="ComfyUI_00001_.png").click(button="right")

            # Open workflow: ComfyUI's own drop path gets the file, with its type, and the dialog closes.
            await menu.get_by_text("Open workflow").click()
            await tab.wait_for_function("window.browserTestFiles.length === 1")
            assert await tab.evaluate("window.browserTestFiles[0]") == {
                "name": "ComfyUI_00001_.png",
                "type": "image/png",
                "size": (output / "ComfyUI_00001_.png").stat().st_size,
            }
            await expect(dialog).not_to_have_attribute("open", "")

            # Send to Load Image from output: a copy is uploaded into input and a new node shows it.
            await open_menu("comfyui-output", "ComfyUI_00001_.png")
            await menu.get_by_text("Send to Load Image").click()
            await tab.wait_for_function("window.browserTestNodes.length === 1")
            node = await tab.evaluate(
                "({type: window.browserTestNodes[0].type, value: window.browserTestNodes[0].widgets[0].value, preview: window.browserTestNodes[0].widgets[0].preview})"
            )
            assert node == {"type": "LoadImage", "value": "ComfyUI_00001_.png", "preview": "ComfyUI_00001_.png"}
            assert app[UPLOADS] == ["ComfyUI_00001_.png"] and (input / "ComfyUI_00001_.png").exists()
            await expect(dialog).not_to_have_attribute("open", "")

            # From input: the file is chosen as it is, in the selected Load Image node, with no upload.
            await open_menu("comfyui-input", "mask.png")
            await menu.get_by_text("Send to Load Image").click()
            await tab.wait_for_function("window.browserTestNodes[0].widgets[0].value === 'mask.png'")
            assert await tab.evaluate("window.browserTestNodes.length") == 1
            assert app[UPLOADS] == ["ComfyUI_00001_.png"]
            assert errors == []
        finally:
            await browser.close()
            await proxy.close()
            await service.close()
