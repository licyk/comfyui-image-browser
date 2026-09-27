"""Register the service with ComfyUI's V3 extension lifecycle."""

import atexit
from pathlib import Path
from urllib.parse import urlsplit

from comfy_api.latest import ComfyExtension

from .events import EVENT_NAME
from .image_roots import collect_image_roots
from .proxy import BrowserProxy
from .runtime.config import combined_view, include_temp, public_base_url
from .service import BrowserService


class ImageBrowserExtension(ComfyExtension):
    async def get_node_list(self) -> list:
        return []

    async def on_load(self) -> None:
        import folder_paths
        from comfy.cli_args import args
        from server import PromptServer

        server = getattr(PromptServer, "instance")
        if getattr(server, "_image_browser_extension", None) is not None:
            return

        def notify() -> None:
            # LoadImage and similar nodes list the input folder; the frontend refreshes their options.
            server.send_sync(EVENT_NAME, {})

        service = BrowserService(
            Path(folder_paths.get_system_user_directory("image_browser")),
            lambda: collect_image_roots(
                folder_paths.get_output_directory(),
                folder_paths.get_input_directory(),
                folder_paths.get_temp_directory() if include_temp() else None,
            ),
            notify,
            public_base_url(),
            combined_view=combined_view(),
        )
        loopback = {"127.0.0.1", "localhost", "::1"}
        listeners = set(args.listen.split(","))
        hosts = loopback.copy() if listeners <= loopback else None
        if hosts is not None and service.public_base_url:
            hostname = urlsplit(service.public_base_url).hostname
            if hostname:
                hosts.add(hostname)
        proxy = BrowserProxy(service, hosts)
        server.routes.get("/image-browser-extension/open")(proxy.open_page)
        server.routes.get("/image-browser-extension/open.js")(proxy.open_script)
        server.routes.get("/image-browser-extension/status")(proxy.status)
        server.routes.post("/image-browser-extension/start")(proxy.start)
        server.routes.post("/image-browser-extension/scan")(proxy.scan)
        server.routes.get("/image-browser")(proxy.handle)
        server.routes.route("*", "/image-browser/{tail:.*}")(proxy.handle)

        async def shutdown(_app) -> None:
            await proxy.close()
            await service.close()
            atexit.unregister(service.stop_at_exit)

        server.app.on_shutdown.append(shutdown)
        atexit.register(service.stop_at_exit)
        server._image_browser_extension = (service, proxy)
