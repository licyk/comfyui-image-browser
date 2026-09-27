import gzip

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer, make_mocked_request

from comfyui_image_browser.proxy import check_origin, scan_folders


@pytest.mark.parametrize("origin", ["https://example.com", "http://example.com", "http://127.0.0.1:8188"])
def test_tls_proxy_requires_the_configured_public_origin(origin):
    request = make_mocked_request("POST", "/image-browser/api/v1/library/delete", headers={"Host": "127.0.0.1:8188", "Origin": origin})
    if origin == "http://example.com":
        with pytest.raises(web.HTTPForbidden):
            check_origin(request, "https://example.com/comfy/image-browser")
    else:
        check_origin(request, "https://example.com/comfy/image-browser")


@pytest.mark.parametrize(
    "host, origin",
    [
        ("example.com", "https://example.com"),
        ("127.0.0.1:8188", "https://comfy.example.com"),
        ("localhost:8188", "https://comfy.example.com:9443"),
    ],
)
@pytest.mark.parametrize("method", ["POST", "GET"])
def test_browser_same_origin_survives_tls_and_host_rewriting(host, origin, method):
    request = make_mocked_request(
        method,
        "/image-browser/api/v1/library/roots",
        headers={"Host": host, "Origin": origin, "Sec-Fetch-Site": "same-origin", **({"Upgrade": "websocket"} if method == "GET" else {})},
    )
    check_origin(request)


@pytest.mark.parametrize(
    "origin, fetch_site",
    [("https://evil.example", "cross-site"), ("https://other.example", "same-site"), ("null", "same-origin"), ("http://[", "same-origin")],
)
def test_cross_site_or_opaque_origins_remain_rejected(origin, fetch_site):
    request = make_mocked_request(
        "POST",
        "/image-browser-extension/start",
        headers={"Host": "localhost:8188", "Origin": origin, "Sec-Fetch-Site": fetch_site, "X-Forwarded-Host": "evil.example"},
    )
    with pytest.raises(web.HTTPForbidden):
        check_origin(request)


def test_cross_site_requests_without_origin_are_rejected():
    # An <img> on another site would otherwise read a thumbnail with the injected token.
    request = make_mocked_request(
        "GET", "/image-browser/api/v1/library/roots/comfyui-output/file", headers={"Sec-Fetch-Site": "cross-site"}
    )
    with pytest.raises(web.HTTPForbidden):
        check_origin(request)
    check_origin(make_mocked_request("GET", "/image-browser/", headers={"Sec-Fetch-Site": "none"}))


def test_result_items_map_to_unique_root_folders():
    folders = scan_folders(
        {
            "items": [
                {"type": "output", "subfolder": ""},
                {"type": "output", "subfolder": ""},
                {"type": "output", "subfolder": "day\\one/"},
                {"type": "input", "subfolder": "masks"},
                {"type": "temp", "subfolder": ""},
                {"type": "output", "subfolder": 3},
                "junk",
            ]
        }
    )
    assert folders == [("comfyui-output", ""), ("comfyui-output", "day/one"), ("comfyui-input", "masks")]
    with pytest.raises(web.HTTPBadRequest):
        scan_folders({"items": "output"})


async def test_streaming_headers_cookies_and_redirect_handling(browser):
    service, _, client, _, _ = browser
    await service.ensure_started()
    real = service._server
    captured = []

    async def upstream(request):
        captured.append(dict(request.headers))
        if request.match_info["tail"] == "redirect":
            raise web.HTTPTemporaryRedirect(location=f"http://{request.host}/image-browser/destination")
        headers = {"Content-Encoding": "gzip", "Content-Type": "text/plain", "Cache-Control": "public, max-age=60"}
        headers["Content-Security-Policy"] = "default-src 'self'"
        return web.Response(body=gzip.compress(b"body compressed once"), headers=headers)

    app = web.Application()
    app.router.add_route("*", "/image-browser/{tail:.*}", upstream)
    async with TestServer(app) as target:

        class Endpoint:
            running = True
            url = str(target.make_url("/image-browser"))

        service._server = Endpoint()
        try:
            response = await client.get(
                "/image-browser/compressed",
                headers={
                    "Authorization": "Bearer external-token",
                    "X-Forwarded-Host": "evil.example",
                    "Cookie": "comfy_session=private; hanaikada_token=guess",
                },
            )
            assert await response.text() == "body compressed once"
            assert response.headers["Cache-Control"] == "public, max-age=60"
            # Overrides a proxy's X-Frame-Options: DENY without dropping Hanaikada's own policy.
            assert response.headers.getall("Content-Security-Policy") == ["default-src 'self'", "frame-ancestors 'self'"]
            assert captured[0]["Authorization"] == "Bearer " + service.token
            assert "X-Forwarded-Host" not in captured[0] and "Cookie" not in captured[0]
            assert captured[0]["Origin"] == str(target.make_url("/")).rstrip("/")
            response = await client.get("/api/image-browser/redirect", allow_redirects=False)
            assert response.status == 307
            assert response.headers["Location"] == "/api/image-browser/destination"
        finally:
            service._server = real


async def test_open_in_file_manager_is_refused_for_remote_browsers(browser):
    service, proxy, client, _, _ = browser
    await service.ensure_started()
    real = service._server
    reached = []

    async def upstream(request):
        reached.append(request.path)
        return web.Response(status=204)

    app = web.Application()
    app.router.add_route("*", "/image-browser/{tail:.*}", upstream)
    async with TestServer(app) as target:

        class Endpoint:
            running = True
            url = str(target.make_url("/image-browser"))

        service._server = Endpoint()
        try:
            # The test client is loopback, so the request passes through...
            response = await client.post("/image-browser/api/v1/library/open", json={"root_id": "comfyui-output", "path": ""})
            assert response.status == 204 and reached == ["/image-browser/api/v1/library/open"]
            # ...but a remote browser must not reach Hanaikada as a loopback client.
            request = make_mocked_request("POST", "/image-browser/api/v1/library/open", headers={"Host": "localhost"})
            response = await proxy.handle(request.clone(remote="192.0.2.10"))
            assert response.status == 403 and b"not_local" in response.body
            assert len(reached) == 1
        finally:
            service._server = real


@pytest.mark.parametrize("chunked", [False, True])
async def test_oversized_upload_is_rejected_without_saving(browser, chunked):
    service, _, client, (output, _), _ = browser
    await service.ensure_started()

    async def body():
        for _ in range(48):
            yield b"x" * (64 * 1024)

    response = await client.put(
        "/image-browser/api/v1/library/upload",
        params={"root_id": "comfyui-output", "name": "large.png"},
        data=body() if chunked else b"x" * (3 * 1024 * 1024),
    )
    assert response.status == 413
    assert not (output / "large.png").exists()
