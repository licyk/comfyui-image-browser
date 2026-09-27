// This module is also discovered by ComfyUI's extension loader; only run on our landing page.
if (/\/image-browser-extension\/open$/.test(window.location.pathname)) {
    const chinese = navigator.language.startsWith("zh");
    const status = document.getElementById("status");
    const retry = document.getElementById("retry");
    const endpoint = new URL("./start", window.location.href);
    retry.textContent = chinese ? "重试" : "Retry";
    async function start() {
        retry.hidden = true;
        status.textContent = chinese ? "正在启动 Hanaikada…" : "Starting Hanaikada…";
        try {
            const response = await fetch(endpoint, { method: "POST", credentials: "same-origin" });
            const body = await response.text();
            let result;
            try { result = JSON.parse(body); } catch { /* Middleware can return HTML. */ }
            if (!response.ok || result?.state !== "ready") {
                const hint = chinese ? "请检查 ComfyUI 日志、登录状态和反向代理配置。" : "Check the ComfyUI log, authentication and proxy configuration.";
                throw new Error(`HTTP ${response.status} · ${endpoint.pathname}. ${typeof result?.error === "string" ? result.error : hint}`);
            }
            window.location.replace(new URL("../image-browser/#/browse", window.location.href));
        } catch (error) {
            status.textContent = String(error.message || error);
            retry.hidden = false;
        }
    }
    retry.onclick = () => void start();
    void start();
}
