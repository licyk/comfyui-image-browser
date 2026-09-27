"""Stream Hanaikada HTTP and Socket.IO traffic through ComfyUI's existing server."""

import asyncio
import contextlib
import ipaddress
import logging
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientSession, ClientTimeout, DummyCookieJar, WSMsgType, web
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from .image_roots import INPUT, OUTPUT, ROOT_IDS
from .service import BROWSER_PREFIX, BrowserService

logger = logging.getLogger("Image-Browser")
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"}
# Opens a file manager on the server's desktop; Hanaikada allows it only for loopback clients.
LOCAL_ONLY = {"api/v1/library/open"}
MAX_SCAN_FOLDERS = 64
NO_STORE = {"Cache-Control": "no-store"}


def check_origin(request: web.Request, public_base_url: str | None = None) -> None:
    """Validate browser provenance before substituting the private upstream origin."""
    origin = request.headers.get("Origin")
    if origin:
        try:
            supplied = URL(origin)
            public = URL(public_base_url) if public_base_url else None
            valid = supplied.scheme in {"http", "https"} and supplied.raw_path in {"", "/"} and not supplied.query_string
            valid = valid and supplied.user is None and not supplied.fragment
            local = valid and supplied.raw_authority.lower() == request.host.lower() and supplied.scheme == request.scheme
            # Browsers compute this before a reverse proxy can rewrite Host or terminate TLS.
            # Unlike forwarding headers, scripts cannot set Sec-Fetch-Site themselves.
            browser_same_origin = valid and request.headers.get("Sec-Fetch-Site") == "same-origin"
            external = valid and public is not None and supplied.origin() == public.origin()
        except ValueError:
            local = external = browser_same_origin = False
        if not (local or external or browser_same_origin):
            raise web.HTTPForbidden(text="Cross-origin image browser request refused")
    elif request.headers.get("Sec-Fetch-Site") not in {None, "same-origin", "none"}:
        raise web.HTTPForbidden(text="Cross-site image browser request refused")


def is_loopback_client(request: web.Request) -> bool:
    try:
        return ipaddress.ip_address((request.remote or "").split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def filtered_headers(headers: CIMultiDict[str] | CIMultiDictProxy[str]) -> CIMultiDict[str]:
    """Remove hop-by-hop headers, including fields named in Connection."""
    result: CIMultiDict[str] = CIMultiDict(headers)
    blocked = HOP_HEADERS | {part.strip().lower() for part in result.get("Connection", "").split(",")}
    for key in list(result):
        if key.lower() in blocked:
            result.popall(key, None)
    return result


def scan_folders(payload: object) -> list[tuple[str, str]]:
    """Map ComfyUI result items ({type, subfolder}) to unique Hanaikada (root id, folder) pairs."""
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise web.HTTPBadRequest(text="Expected {items: [{type, subfolder}]}")
    folders: dict[tuple[str, str], None] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("type") not in {OUTPUT, INPUT}:
            continue
        subfolder = item.get("subfolder") or ""
        if not isinstance(subfolder, str):
            continue
        # Hanaikada validates the path again; this only normalises ComfyUI's separators.
        folders[(ROOT_IDS[item["type"]], subfolder.replace("\\", "/").strip("/"))] = None
        if len(folders) >= MAX_SCAN_FOLDERS:
            break
    return list(folders)


class BrowserProxy:
    def __init__(self, service: BrowserService, allowed_hosts: set[str] | None = None) -> None:
        self.service = service
        self.allowed_hosts = allowed_hosts
        self._session: ClientSession | None = None
        self._websockets: set[web.WebSocketResponse] = set()

    def validate(self, request: web.Request) -> None:
        if self.allowed_hosts is not None and URL(f"http://{request.host}").host not in self.allowed_hosts:
            raise web.HTTPForbidden(text="Image browser host is not allowed")
        check_origin(request, self.service.public_base_url)

    def session(self) -> ClientSession:
        if self._session is None:
            self._session = ClientSession(
                cookie_jar=DummyCookieJar(),
                auto_decompress=False,
                trust_env=False,
                timeout=ClientTimeout(total=None, sock_connect=10),
            )
        return self._session

    async def open_page(self, request: web.Request) -> web.Response:
        """A read-only landing page starts Hanaikada from its own top-level browser origin."""
        # Navigation may originate in a sandboxed/embedded ComfyUI. Do not start the
        # service here: the page's POST still goes through the normal origin check.
        page = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Hanaikada</title>
<style>body{font:16px system-ui;margin:3rem;line-height:1.6;color-scheme:light dark}
button{font:inherit;padding:.4rem 1rem}p{white-space:pre-wrap}</style></head><body>
<h1>Hanaikada</h1><p id="status" role="status"></p><button id="retry" hidden></button>
<script type="module" src="open.js"></script></body></html>"""
        return web.Response(
            text=page,
            content_type="text/html",
            headers={
                **NO_STORE,
                "Referrer-Policy": "same-origin",
                "Content-Security-Policy": "frame-ancestors 'self'",
            },
        )

    async def open_script(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(Path(__file__).resolve().parents[1] / "js" / "standalone.js", headers=NO_STORE)

    async def status(self, request: web.Request) -> web.Response:
        try:
            self.validate(request)
        except web.HTTPException as exc:
            return web.json_response({"state": "failed", "error": exc.text}, status=exc.status, headers=NO_STORE)
        return web.json_response(self.service.status(), headers=NO_STORE)

    async def start(self, request: web.Request) -> web.Response:
        try:
            self.validate(request)
        except web.HTTPException as exc:
            return web.json_response({"state": "failed", "error": exc.text}, status=exc.status, headers=NO_STORE)
        try:
            await self.service.ensure_started()
        except Exception:
            return web.json_response(self.service.status(), status=503, headers=NO_STORE)
        return web.json_response(self.service.status(), headers=NO_STORE)

    async def scan(self, request: web.Request) -> web.Response:
        """Index ComfyUI's new results now; a stopped browser finds them when it starts."""
        self.validate(request)
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise web.HTTPBadRequest(text="Expected a JSON body") from None
        queued = await self.service.scan(scan_folders(payload))
        return web.json_response({"queued": queued}, headers=NO_STORE)

    async def handle(self, request: web.Request) -> web.StreamResponse:
        self.validate(request)
        if self.service.status()["state"] != "ready":
            return web.json_response({"error": "Open the image browser to start Hanaikada", **self.service.status()}, status=503)
        upstream = self.service.upstream
        # Use the raw path to preserve encoded filenames. The destination origin is always ours.
        raw = request.rel_url.raw_path
        marker = BROWSER_PREFIX + "/"
        if marker not in raw:
            raise web.HTTPTemporaryRedirect(location=raw + "/")
        tail = raw.split(marker, 1)[1]
        if any(part in {".", ".."} for part in request.path.split("/")):
            raise web.HTTPBadRequest(text="Invalid image browser path")
        if request.path.split(marker, 1)[1].rstrip("/") in LOCAL_ONLY and not is_loopback_client(request):
            # Upstream, every proxied request comes from loopback; keep Hanaikada's own rule.
            message = "Opening files works only in a browser on the server's own machine"
            return web.json_response({"code": "not_local", "message": message, "detail": {}}, status=403)
        url = URL(upstream + "/" + tail + ("?" + request.rel_url.raw_query_string if request.query_string else ""), encoded=True)
        headers = filtered_headers(request.headers)
        for key in list(headers):
            lower = key.lower()
            if lower in {"host", "authorization", "cookie", "origin", "referer", "forwarded"} or lower.startswith(
                ("x-forwarded-", "sec-websocket-")
            ):
                headers.popall(key, None)
        headers["Host"] = url.raw_authority
        headers["Origin"] = str(url.origin())
        headers["Authorization"] = "Bearer " + self.service.token
        try:
            if request.headers.get("Upgrade", "").lower() == "websocket":
                return await self._socket(request, url, headers)
            return await self._http(request, url, headers)
        except (ClientError, TimeoutError, OSError) as exc:
            if isinstance(exc.__cause__, web.HTTPRequestEntityTooLarge):
                raise exc.__cause__
            logger.warning("Hanaikada connection interrupted: %s", type(exc).__name__)
            return web.json_response({"error": "Hanaikada connection failed; reopen the image browser to retry"}, status=502)

    async def _http(self, request: web.Request, url: URL, headers: CIMultiDict[str]) -> web.StreamResponse:
        limit = request.client_max_size
        if limit and request.content_length is not None and request.content_length > limit:
            raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=request.content_length)

        async def body():
            total = 0
            async for chunk in request.content.iter_chunked(256 * 1024):
                total += len(chunk)
                if limit and total > limit:
                    raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=total)
                yield chunk

        async with self.session().request(
            request.method,
            url,
            headers=headers,
            data=body() if request.can_read_body else None,
            allow_redirects=False,
        ) as upstream:
            response_headers = filtered_headers(upstream.headers)
            # Browsers ignore X-Frame-Options when a response carries frame-ancestors, so a proxy's
            # X-Frame-Options: DENY no longer blocks the ComfyUI dialog. A separate CSP only adds
            # restrictions: any policy from Hanaikada or the proxy still applies.
            response_headers.add("Content-Security-Policy", "frame-ancestors 'self'")
            location = response_headers.get("Location")
            if location:
                internal = str(url.origin())
                if location.startswith(internal + "/"):
                    location = location[len(internal) :]
                public_path = (
                    urlsplit(self.service.public_base_url).path.rstrip("/")
                    if self.service.public_base_url
                    else request.path.split(BROWSER_PREFIX, 1)[0] + BROWSER_PREFIX
                )
                if location == BROWSER_PREFIX or location.startswith(BROWSER_PREFIX + "/"):
                    location = public_path + location[len(BROWSER_PREFIX) :]
                response_headers["Location"] = location
            response = web.StreamResponse(status=upstream.status, headers=response_headers)
            await response.prepare(request)
            try:
                async for chunk in upstream.content.iter_chunked(256 * 1024):
                    await response.write(chunk)
                await response.write_eof()
            except (ClientError, ConnectionError):
                # Headers are already sent; terminate the stream instead of writing a second response.
                response.force_close()
                if request.transport:
                    request.transport.close()
            return response

    async def _socket(self, request: web.Request, url: URL, headers: CIMultiDict[str]) -> web.WebSocketResponse:
        protocols = [item.strip() for item in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if item.strip()]
        async with self.session().ws_connect(url, headers=headers, protocols=protocols, max_msg_size=0) as upstream:
            downstream = web.WebSocketResponse(protocols=[upstream.protocol] if upstream.protocol else (), max_msg_size=0)
            await downstream.prepare(request)
            self._websockets.add(downstream)

            async def relay(source, target):
                async for message in source:
                    if message.type == WSMsgType.TEXT:
                        await target.send_str(message.data)
                    elif message.type == WSMsgType.BINARY:
                        await target.send_bytes(message.data)
                    elif message.type == WSMsgType.ERROR:
                        break

            tasks = [asyncio.create_task(relay(downstream, upstream)), asyncio.create_task(relay(upstream, downstream))]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                with contextlib.suppress(ConnectionError):
                    await downstream.close(code=upstream.close_code or 1000)
                self._websockets.discard(downstream)
            return downstream

    async def close(self) -> None:
        for socket in tuple(self._websockets):
            await socket.close(code=1001, message=b"ComfyUI is shutting down")
        if self._session is not None:
            await self._session.close()
            self._session = None
