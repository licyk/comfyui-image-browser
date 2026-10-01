# ComfyUI Image Browser

[中文说明](README-zh.md)

An image browser for ComfyUI, powered by [Hanaikada](https://github.com/licyk/Hanaikada).

Open Hanaikada inside ComfyUI using the **Lucide Images** toolbar button (tooltip: **Image Browser**). Browse, search, tag, compare and manage the images ComfyUI generates, with every prompt, seed, model and sampler read back from the workflow ComfyUI saved into each file.

- Opens ComfyUI's `output` folder, with `input` as a second folder. Both follow `--output-directory`, `--input-directory` and `--base-directory`.
- **All folders** is where the browser opens: ComfyUI's `output` and `input` side by side. The extension keeps it on, so Hanaikada's settings switch has no effect; `COMFYUI_IMAGE_BROWSER_COMBINED_VIEW=0` turns it off, and Browse then opens on `output`.
- New results appear as soon as a prompt finishes: the extension asks Hanaikada to index the folders ComfyUI just wrote to, instead of waiting for its folder watcher.
- Uploading, copying, moving, renaming or deleting files in `input` refreshes the image lists of nodes such as **Load Image**.
- **Open workflow** (in an image's menu or the viewer's Send button) opens the workflow saved in a ComfyUI PNG, WebP or AVIF, or the parameters of a WebUI PNG, in a new workflow tab; the current workflow is left as it was.
- **Send to Load Image** puts the image in the selected **Load Image** node, or a new one: a file from `output` is uploaded to `input` as a copy, a file already in `input` is chosen as it is.
- Closing the window keeps its folder, search and viewer; reopening shows them again.
- Starts Hanaikada on demand, with no scan during ComfyUI startup.
- Reuses the dependency installation framework from [ComfyUI-HakuImg](https://github.com/licyk/ComfyUI-HakuImg). No Node.js build is needed.

## Installation

From the ComfyUI directory, clone the extension using Git:

```bash
git clone https://github.com/licyk/comfyui-image-browser.git custom_nodes/comfyui-image-browser
```

Restart ComfyUI and refresh the browser. The prestartup script automatically installs missing/incompatible dependencies using ComfyUI's own Python interpreter.

## Behavior

Use the toolbar button or **Tools → Open Image Browser**. The window opens Hanaikada's Browse page on **All folders** and supports maximize, close and retry. Press Escape with nothing focused in the browser to close it; inside the browser, Escape first clears a selection or closes a menu, drawer or the viewer.

The toolbar button uses the frontend's action bar, or the legacy top menu on older frontends. **Open in new tab** is always available in the dialog header, including after startup failure. The new tab starts Hanaikada independently from its own origin before opening the browser.

The folders are fixed by ComfyUI: Hanaikada cannot add, change or remove them, so the browser never reaches beyond ComfyUI's own image folders. Set `COMFYUI_IMAGE_BROWSER_INCLUDE_TEMP=1` to also browse the `temp` folder (previews), which ComfyUI empties on every start; it is browsed but not indexed. Restart after changing ComfyUI's directory options.

Hanaikada's index, thumbnails and settings live under `<ComfyUI user directory>/__image_browser/`, separate from the extension and from a standalone Hanaikada.

Startup errors show the HTTP status and request path. For 404 / 405, check extension loading and proxy routes; for 401 / 403, check authentication and the public URL configuration. A 200 response without a start-up result may be a login page or frontend HTML. Restart ComfyUI and hard-refresh the browser after updating the extension.

## Remote access

All browser traffic uses ComfyUI's same-origin `/image-browser/` path. The private Hanaikada server binds a random loopback port and is authenticated using a backend-only token. The proxy supports streaming HTTP (uploads, zip downloads, thumbnails), WebSocket and Socket.IO polling. No additional public port is needed.

Forward the entire ComfyUI deployment path, including WebSocket upgrades. Valid browser origins accompanied by `Sec-Fetch-Site: same-origin` remain accepted after proxy TLS termination or Host rewriting. Cross-site and opaque (`Origin: null`) requests remain rejected; use **Open in new tab** if ComfyUI is embedded in a sandbox or another website.

The dialog embeds `/image-browser/` in a same-origin iframe. Proxied responses carry `Content-Security-Policy: frame-ancestors 'self'`, so browsers ignore an `X-Frame-Options: DENY` that a reverse proxy or CDN adds. A restrictive `frame-ancestors` in the proxy's own `Content-Security-Policy`, or a proxy that strips or replaces backend CSP headers, still blocks the embed, and the dialog reports the refused framing. Allow `frame-ancestors 'self'` for the ComfyUI host, or use **Open in new tab**.

For proxies that remove browser origin metadata, set the public URL of the browser, including any proxy prefix:

```bash
export COMFYUI_IMAGE_BROWSER_PUBLIC_BASE_URL=https://example.com/comfy/image-browser
```

The browser inherits access to ComfyUI: anyone who can use ComfyUI can view, move and delete its images. ComfyUI user IDs do not provide separate authorization. Existing deployment authentication must cover both HTTP and WebSocket paths. **Open in file manager** only works for a browser on the server's own machine, as in a standalone Hanaikada.

**All folders** is fixed on; set `COMFYUI_IMAGE_BROWSER_COMBINED_VIEW=0` to fix it off instead.

Set `COMFYUI_IMAGE_BROWSER_AUTO_INSTALL=0` to manage dependencies manually. Installer logging can be configured through `COMFYUI_IMAGE_BROWSER_LOGGER_NAME`, `COMFYUI_IMAGE_BROWSER_LOGGER_LEVEL` (default `20`) and `COMFYUI_IMAGE_BROWSER_LOGGER_COLOR` (`0` disables color).

## Development

```bash
python -m playwright install chromium
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m ty check --python /path/to/comfy/python
node --check js/image_browser.js
node --test tests/*.mjs
```

Type checking expects ComfyUI at `../ComfyUI`; otherwise pass `--extra-search-path /path/to/ComfyUI`. Browser tests optionally accept `PLAYWRIGHT_CHROMIUM_EXECUTABLE`.

Tests use the released Hanaikada, temporary ComfyUI folders and images carrying ComfyUI's metadata. Chromium tests use the real Hanaikada UI inside a small host implementing the public ComfyUI extension registration contract. They do not substitute for a full ComfyUI frontend/GPU workflow check.

Licensed under [GPL-3.0-only](LICENSE).
