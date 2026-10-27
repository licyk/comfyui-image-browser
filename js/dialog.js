// Keep the browser iframe alive while hidden so its folder, search and viewer survive closing.
// The panel is not modal: the canvas underneath stays usable while it is open, which is what
// makes dragging a picture out of it and onto the canvas possible.
const SIZE_KEY = "comfy-image-browser.panel-size";

function storedSize() {
    try {
        const size = JSON.parse(localStorage.getItem(SIZE_KEY) ?? "null");
        if (Number.isFinite(size?.width) && Number.isFinite(size?.height)) return size;
    } catch {
        // Storage may be denied; the panel then keeps its default size.
    }
    return null;
}

function applySize(dialog, size) {
    dialog.style.width = size ? `${size.width}px` : "";
    dialog.style.height = size ? `${size.height}px` : "";
}

// The header drags the panel; resizing is the browser's own bottom-right corner handle.
function makeDraggable(dialog, handle) {
    handle.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || event.target.closest("button, a")) return;
        const box = dialog.getBoundingClientRect();
        // Leave the centred layout behind, so left/top can follow the pointer.
        dialog.classList.add("comfy-image-browser-placed");
        dialog.style.left = `${box.left}px`;
        dialog.style.top = `${box.top}px`;
        dialog.style.width = `${box.width}px`;
        dialog.style.height = `${box.height}px`;
        const startX = event.clientX;
        const startY = event.clientY;
        const move = (moveEvent) => {
            dialog.style.left = `${box.left + moveEvent.clientX - startX}px`;
            dialog.style.top = `${box.top + moveEvent.clientY - startY}px`;
        };
        const stop = () => {
            handle.removeEventListener("pointermove", move);
            handle.removeEventListener("pointerup", stop);
            handle.removeEventListener("pointercancel", stop);
            if (handle.hasPointerCapture?.(event.pointerId)) handle.releasePointerCapture(event.pointerId);
        };
        handle.setPointerCapture?.(event.pointerId);
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", stop);
        handle.addEventListener("pointercancel", stop);
        event.preventDefault();
    });
}

export function createBrowserDialog({ start, url, standaloneUrl, text }) {
    let loaded = false;
    let opening = null;
    let previousFocus = null;
    let revision = 0;
    const dialog = document.createElement("dialog");
    dialog.className = "comfy-image-browser";
    dialog.setAttribute("aria-label", text.title);
    const header = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = text.title;
    const maximize = document.createElement("button");
    maximize.type = "button";
    maximize.textContent = text.maximize;
    maximize.setAttribute("aria-pressed", "false");
    maximize.onclick = () => {
        const expanded = dialog.classList.toggle("comfy-image-browser-maximized");
        // Maximising has its own size; the panel's own size comes back when it is restored.
        if (expanded) {
            dialog.classList.remove("comfy-image-browser-placed");
            dialog.style.left = "";
            dialog.style.top = "";
            applySize(dialog, null);
        } else {
            applySize(dialog, storedSize());
        }
        maximize.setAttribute("aria-pressed", String(expanded));
        maximize.textContent = expanded ? text.restore : text.maximize;
    };
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = text.close;
    close.onclick = () => dialog.close();
    const newTab = document.createElement("a");
    newTab.href = standaloneUrl();
    newTab.target = "_blank";
    newTab.rel = "noopener noreferrer";
    newTab.textContent = text.newTab;
    header.append(title, newTab, maximize, close);
    const status = document.createElement("div");
    status.className = "comfy-image-browser-status";
    status.setAttribute("role", "status");
    status.hidden = true;
    const message = document.createElement("p");
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = text.retry;
    retry.hidden = true;
    retry.onclick = () => void open(true);
    status.append(message, retry);
    const frame = document.createElement("iframe");
    frame.title = text.title;
    frame.hidden = true;
    frame.setAttribute("referrerpolicy", "same-origin");
    // Same-origin embedding lets the dialog detect refused framing and forward Escape.
    dialog.append(header, status, frame);
    document.body.append(dialog);
    applySize(dialog, storedSize());
    makeDraggable(dialog, header);
    if (typeof ResizeObserver === "function") {
        // Remember whatever size the user leaves behind, including the corner handle's.
        new ResizeObserver(() => {
            if (dialog.classList.contains("comfy-image-browser-maximized")) return;
            const box = dialog.getBoundingClientRect();
            if (!box.width || !box.height) return;
            try {
                localStorage.setItem(SIZE_KEY, JSON.stringify({ width: Math.round(box.width), height: Math.round(box.height) }));
            } catch {
                // Storage may be denied; the next open then uses the default size.
            }
        }).observe(dialog);
    }
    let timeout;

    function failed(error) {
        clearTimeout(timeout);
        loaded = false;
        status.hidden = false;
        frame.hidden = true;
        message.textContent = `${text.failed} ${error.message || error}`;
        retry.hidden = false;
    }

    frame.addEventListener("load", () => {
        if (!frame.hasAttribute("src")) return;
        clearTimeout(timeout);
        // X-Frame-Options / CSP frame-ancestors refusals still fire load, leaving an
        // inaccessible or never-navigated document instead of the browser page.
        let doc = null;
        try { doc = frame.contentDocument; } catch { doc = null; }
        if (!doc || doc.location.href === "about:blank") {
            failed(new Error(text.framing));
            return;
        }
        if (!doc.querySelector("#app")) {
            failed(new Error(text.unavailable));
            return;
        }
        loaded = true;
        status.hidden = true;
        frame.hidden = false;
        // Hanaikada uses Escape itself (selection, menus, drawers, viewer), so only an Escape
        // that reaches no focused control and no open overlay closes the dialog.
        doc.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !event.defaultPrevented &&
                (event.target === doc.body || event.target === doc.documentElement) &&
                !doc.querySelector('md-dialog[open], dialog[open], [role="dialog"][aria-modal="true"], [role="menu"]')) {
                event.preventDefault();
                dialog.close();
            }
        });
    });
    frame.addEventListener("error", () => failed(new Error(text.unavailable)));
    dialog.addEventListener("close", () => previousFocus?.focus?.());

    async function open(forceReload = false) {
        if (!dialog.open) {
            previousFocus = document.activeElement;
            // Non-modal on purpose: the canvas has to stay reachable for a drop.
            dialog.show();
        }
        if (opening) return opening;
        opening = (async () => {
            if (!loaded || forceReload) {
                message.textContent = text.loading;
                retry.hidden = true;
                status.hidden = false;
                frame.hidden = true;
            }
            try {
                await start();
                if (!loaded || forceReload) {
                    const target = new URL(url(), window.location.href);
                    // Reassigning an identical hash URL only navigates within the document;
                    // retry must load a fresh document so its load event fires again.
                    if (frame.hasAttribute("src")) target.searchParams.set("_comfyui_browser_reload", String(++revision));
                    frame.src = target.href;
                    clearTimeout(timeout);
                    timeout = setTimeout(() => failed(new Error(text.unavailable)), 45000);
                }
            } catch (error) {
                failed(error);
            }
        })();
        try { await opening; } finally { opening = null; }
    }

    // The frame lets the extension answer only its own Hanaikada; close hides the dialog after a send.
    return { open, close: () => dialog.close(), frame };
}
