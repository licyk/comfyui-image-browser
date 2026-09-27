// Pure helpers for answering Hanaikada's host bridge (protocol v1, see Hanaikada's
// webui/src/host/bridge.ts), kept apart from image_browser.js so tests can import them.

export const NS = "hanaikada";
export const PROTOCOL = 1;

// What ComfyUI takes from the browser. Hanaikada names both ids itself and shows only matching
// targets: "Open workflow" for images a workflow can be read from, "Send to Load Image" for any image.
export const TARGETS = [
    { id: "workflow", kinds: ["image"], platforms: ["comfyui", "sd-webui"], needs: ["file"] },
    { id: "loadImage", kinds: ["image"], needs: ["file"] },
];

// The root ids the extension gives ComfyUI's folders (comfyui_image_browser/image_roots.py).
export const INPUT_ROOT = "comfyui-input";

export function isBridgeMessage(data) {
    return !!data && typeof data === "object" && data.ns === NS && data.v === PROTOCOL && typeof data.type === "string";
}

const extension = (name) => String(name ?? "").toLowerCase().split(".").pop();

// ComfyUI reads a workflow from its own PNG, WebP and AVIF files, and imports a WebUI PNG's
// parameters; anything else (a WebUI JPEG, a WebP with only a UserComment) would become a bare
// LoadImage node instead of a workflow, so it is refused with a message.
export function canOpenWorkflow(name, platform) {
    const ext = extension(name);
    if (platform === "comfyui") return ["png", "webp", "avif"].includes(ext);
    if (platform === "sd-webui") return ext === "png";
    return false;
}

// A file already in ComfyUI's input folder is chosen as it is ("sub/name.png"); anything else is
// uploaded as a copy. Null means "upload".
export function inputValue(item) {
    if (!item || item.root_id !== INPUT_ROOT || typeof item.path !== "string" || !item.path) return null;
    return item.path.replace(/\\/g, "/").replace(/^\/+/, "");
}

// A well-formed send request, or null.
export function sendRequest(data) {
    if (!isBridgeMessage(data) || data.type !== "send" || typeof data.id !== "string" || typeof data.target !== "string") return null;
    const item = data.payload?.item;
    if (!item || typeof item.url !== "string" || typeof item.name !== "string") return null;
    return { id: data.id, target: data.target, item, platform: data.payload.platform ?? null };
}
