import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { createBrowserDialog } from "./dialog.js";
import { hasActionBar, resultItems } from "./frontend.js";
import { canOpenWorkflow, inputValue, isBridgeMessage, NS, PROTOCOL, sendRequest, TARGETS } from "./host.js";
import { readStartupResponse } from "./startup.js";

const translations = {
    en: {
        title: "Image Browser", maximize: "Maximize", restore: "Restore", close: "Close", retry: "Retry", newTab: "Open in new tab",
        loading: "Starting Hanaikada…", failed: "Unable to open Image Browser.",
        unavailable: "The interface did not load. Check the ComfyUI log and retry.",
        framing: "The browser refused to embed the interface. A reverse proxy is sending X-Frame-Options: deny "
            + "or a Content-Security-Policy frame-ancestors rule for this address. Allow same-origin embedding "
            + "(X-Frame-Options: SAMEORIGIN, or frame-ancestors 'self'), or use Open in new tab.",
        startup: {
            notJson: "The server returned a non-JSON response.",
            missing: "The extension startup endpoint was not found. Restart ComfyUI and check its extension loading log and proxy routes.",
            denied: "The startup request was denied or redirected to login. Check authentication and the configured public URL when using a reverse proxy.",
            unexpected: "The request did not return a Hanaikada start-up result. Check whether a proxy or frontend page is handling this address.",
            server: "The backend could not start Hanaikada. Check the ComfyUI log for the underlying error.",
        },
        send: {
            noWorkflow: "ComfyUI reads workflows from its own PNG, WebP and AVIF files and from WebUI PNGs; this file has none it can open.",
            noNode: "Could not add a Load Image node to the workflow.",
            uploadFailed: "Uploading the image to ComfyUI's input folder failed:",
            foreign: "Only files from this ComfyUI's image browser can be sent.",
            unknown: "ComfyUI does not take this.",
        },
    },
    zh: {
        title: "图片浏览器", maximize: "最大化", restore: "还原", close: "关闭", retry: "重试", newTab: "在新标签页打开",
        loading: "正在启动 Hanaikada…", failed: "无法打开图片浏览器。",
        unavailable: "界面未能加载，请检查 ComfyUI 日志后重试。",
        framing: "浏览器拒绝嵌入该界面。反向代理为该地址返回了 X-Frame-Options: deny 或 "
            + "Content-Security-Policy 的 frame-ancestors 限制。请允许同源嵌入"
            + "（X-Frame-Options: SAMEORIGIN 或 frame-ancestors 'self'），或使用“在新标签页打开”。",
        startup: {
            notJson: "服务器返回的内容不是 JSON。",
            missing: "未找到扩展启动接口。请重启 ComfyUI，并检查扩展加载日志和反向代理路由。",
            denied: "启动请求被拒绝或被重定向到登录页。请检查登录状态；使用反向代理时，请核对配置的外部地址。",
            unexpected: "该地址没有返回 Hanaikada 启动结果，请检查请求是否被代理或前端页面接管。",
            server: "后端未能启动 Hanaikada，请检查 ComfyUI 日志中的具体错误。",
        },
        send: {
            noWorkflow: "ComfyUI 只能从它自己的 PNG、WebP、AVIF 文件以及 WebUI 的 PNG 中读取工作流；这个文件里没有可打开的工作流。",
            noNode: "无法在工作流中添加“加载图像”节点。",
            uploadFailed: "上传图片到 ComfyUI 的 input 文件夹失败：",
            foreign: "只能发送来自此 ComfyUI 图片浏览器的文件。",
            unknown: "ComfyUI 不接受该操作。",
        },
    },
};

function text() {
    const locale = app.extensionManager?.setting?.get("Comfy.Locale") || navigator.language;
    return translations[String(locale).startsWith("zh") ? "zh" : "en"];
}

let panel;
function open() {
    panel ??= createBrowserDialog({
        text: text(),
        url: () => api.fileURL("/image-browser/#/browse"),
        standaloneUrl: () => api.fileURL("/image-browser-extension/open"),
        start: async () => {
            const response = await api.fetchApi("/image-browser-extension/start", { method: "POST" });
            await readStartupResponse(response, api.apiURL("/image-browser-extension/start"), text().startup);
        },
    });
    return panel.open();
}

// -- Hanaikada's "Send to …": its host bridge (protocol v1) -------------------------------------

function reply(target, message) {
    target.postMessage({ ns: NS, v: PROTOCOL, ...message }, window.location.origin);
}

async function fetchFile(item) {
    const url = new URL(item.url, window.location.href);
    // Only files this ComfyUI serves through the browser's own proxy.
    if (url.origin !== window.location.origin) throw new Error(text().send.foreign);
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    // ComfyUI's file readers dispatch on the MIME type.
    return new File([blob], item.name, { type: blob.type || response.headers.get("Content-Type") || "" });
}

// ComfyUI's own drop path reads the workflow (or the API prompt, or a WebUI PNG's parameters) and
// opens it in a new workflow tab named after the file; the current workflow stays as it was.
async function openWorkflow(item, platform) {
    if (!canOpenWorkflow(item.name, platform)) throw new Error(text().send.noWorkflow);
    await app.handleFile(await fetchFile(item));
}

// A copy in ComfyUI's input folder, through its public upload route (an identical file already
// there is reused under its name).
async function uploadCopy(item) {
    const body = new FormData();
    body.append("image", await fetchFile(item));
    body.append("type", "input");
    const response = await api.fetchApi("/upload/image", { method: "POST", body });
    if (response.status !== 200) throw new Error(`${text().send.uploadFailed} HTTP ${response.status}`);
    const data = await response.json();
    return data.subfolder ? `${data.subfolder}/${data.name}` : data.name;
}

function visibleCenter(canvas) {
    try {
        const [x, y] = canvas.ds.convertCanvasToOffset([canvas.canvas.clientWidth / 2, canvas.canvas.clientHeight / 2]);
        return [x - 160, y - 160];
    } catch {
        return [0, 0];
    }
}

// The selected Load Image node, or a new one in the middle of the view.
function loadImageNode() {
    const canvas = app.canvas;
    const selected = Object.values(canvas?.selected_nodes ?? {}).filter((node) => (node.comfyClass ?? node.type) === "LoadImage");
    if (selected.length === 1) return selected[0];
    const graph = canvas?.graph ?? app.graph;
    const node = window.LiteGraph?.createNode("LoadImage");
    if (!node || !graph) throw new Error(text().send.noNode);
    node.pos = visibleCenter(canvas);
    graph.add(node);
    canvas?.selectNode?.(node);
    return node;
}

async function sendToLoadImage(item) {
    const existing = inputValue(item);
    const value = existing ?? (await uploadCopy(item));
    const node = loadImageNode();
    const widget = node.widgets?.find((w) => w.name === "image");
    if (!widget) throw new Error(text().send.noNode);
    const values = widget.options?.values;
    if (Array.isArray(values) && !values.includes(value)) values.push(value);
    widget.value = value;
    // The frontend's own callback on this widget loads the preview.
    widget.callback?.(value);
    node.setDirtyCanvas?.(true, true);
    // Other Load Image nodes list the new file too.
    if (existing === null) void refresh();
}

function answerHanaikada(event) {
    const frame = panel?.frame;
    if (!frame || event.source !== frame.contentWindow || event.origin !== window.location.origin || !isBridgeMessage(event.data)) return;
    if (event.data.type === "hello") {
        reply(event.source, { type: "host", host: { name: "comfyui", label: "ComfyUI", targets: TARGETS } });
        return;
    }
    const request = sendRequest(event.data);
    if (!request) return;
    const source = event.source;
    void (async () => {
        try {
            if (request.target === "workflow") await openWorkflow(request.item, request.platform);
            else if (request.target === "loadImage") await sendToLoadImage(request.item);
            else throw new Error(text().send.unknown);
            reply(source, { type: "result", id: request.id, ok: true });
            // Back to the canvas, where the new tab or node now is.
            panel.close();
        } catch (error) {
            reply(source, { type: "result", id: request.id, ok: false, message: error?.message || String(error) });
        }
    })();
}

let refreshTimer;
let refreshing = false;
let dirty = false;
async function refresh() {
    dirty = true;
    if (refreshing) return;
    refreshing = true;
    try {
        while (dirty) {
            dirty = false;
            if (app.extensionManager?.command?.execute) {
                await app.extensionManager.command.execute("Comfy.RefreshNodeDefinitions");
            } else {
                await app.refreshComboInNodes();
            }
        }
    } catch (error) {
        console.warn("[ComfyUI Image Browser] Node input refresh failed", error);
    } finally { refreshing = false; }
}

// New results reach the browser at once instead of at the next folder poll.
let pendingScan = new Map();
let scanTimer;
function queueScan(items) {
    for (const item of items) pendingScan.set(`${item.type}\n${item.subfolder}`, item);
    if (!pendingScan.size || scanTimer) return;
    scanTimer = setTimeout(async () => {
        const batch = [...pendingScan.values()];
        pendingScan = new Map();
        scanTimer = undefined;
        try {
            await api.fetchApi("/image-browser-extension/scan", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ items: batch }),
            });
        } catch {
            // Best effort: Hanaikada's own folder watcher still finds the files.
        }
    }, 500);
}

// Older frontends have no action bar API; their top menu takes a ComfyButton instead.
async function addLegacyButton() {
    try {
        const [{ ComfyButton }, { ComfyButtonGroup }] = await Promise.all([
            import("../../scripts/ui/components/button.js"),
            import("../../scripts/ui/components/buttonGroup.js"),
        ]);
        const icon = document.createElement("i");
        icon.className = "icon-[lucide--images] comfy-image-browser-icon";
        icon.setAttribute("aria-hidden", "true");
        const button = new ComfyButton({
            action: () => void open(), tooltip: text().title, content: icon,
            classList: "comfyui-button comfyui-menu-mobile-collapse comfy-image-browser-button",
        });
        button.element.setAttribute("aria-label", text().title);
        const group = new ComfyButtonGroup(button.element);
        app.menu.settingsGroup.element.before(group.element);
        return true;
    } catch {
        return false;
    }
}

app.registerExtension({
    name: "ComfyUI.ImageBrowser",
    commands: [{ id: "ComfyUI.ImageBrowser.Open", label: "Open Image Browser", function: open }],
    menuCommands: [{ path: ["Tools"], commands: ["ComfyUI.ImageBrowser.Open"] }],
    async setup() {
        const style = document.createElement("link");
        style.rel = "stylesheet";
        style.href = new URL("./image_browser.css", import.meta.url).href;
        document.head.append(style);
        api.addEventListener("comfyui-image-browser.inputs-changed", () => {
            clearTimeout(refreshTimer);
            refreshTimer = setTimeout(() => void refresh(), 400);
        });
        api.addEventListener("executed", (event) => queueScan(resultItems(event.detail?.output)));
        window.addEventListener("message", answerHanaikada);
        // Newer frontends log every import of the deprecated legacy button modules.
        const legacy = !hasActionBar(window.__COMFYUI_FRONTEND_VERSION__) && app.menu?.settingsGroup?.element;
        if (!legacy || !(await addLegacyButton())) {
            app.registerExtension({
                name: "ComfyUI.ImageBrowser.Toolbar",
                actionBarButtons: [{
                    icon: "icon-[lucide--images]", tooltip: text().title,
                    class: "comfy-image-browser-button", onClick: () => void open(),
                }],
            });
        }
    },
});
