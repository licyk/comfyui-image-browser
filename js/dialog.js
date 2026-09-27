// Keep the browser iframe alive while hidden so its folder, search and viewer survive closing.
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
    const message = document.createElement("p");
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = text.retry;
    retry.onclick = () => void open(true);
    status.append(message, retry);
    const frame = document.createElement("iframe");
    frame.title = text.title;
    frame.hidden = true;
    frame.setAttribute("referrerpolicy", "same-origin");
    // Same-origin embedding lets the dialog detect refused framing and forward Escape.
    dialog.append(header, status, frame);
    document.body.append(dialog);
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
            dialog.showModal();
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
