import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { createBrowserDialog } from "./dialog.js";
import { hasActionBar, resultItems } from "./frontend.js";
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
