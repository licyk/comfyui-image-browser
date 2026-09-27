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
const settings = document.createElement('div');
document.body.append(settings);
export const app = {
    menu: {settingsGroup: {element: settings}},
    extensionManager: {
        setting: {get: () => 'en'},
        command: {execute: async () => {window.browserTestRefreshes++;}},
    },
    async registerExtension(extension) {
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


def script(body: str):
    async def handler(_):
        return web.Response(text=body, content_type="text/javascript")

    return handler


def harness(service: BrowserService, proxy: BrowserProxy, frontend_version: str | None = None) -> tuple[web.Application, list[str]]:
    """A page loading the extension like ComfyUI does; records which legacy modules it imports."""
    app = web.Application()
    legacy_imports: list[str] = []
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
