// Pure helpers, kept apart from image_browser.js so tests can import them without ComfyUI.
// Results a node saved; ComfyUI reports each as {filename, subfolder, type} under any output key.
export function resultItems(output) {
    const items = [];
    for (const value of Object.values(output ?? {})) {
        if (!Array.isArray(value)) continue;
        for (const item of value) {
            if (item && typeof item === "object" && typeof item.filename === "string" && (item.type === "output" || item.type === "input")) {
                items.push({ type: item.type, subfolder: typeof item.subfolder === "string" ? item.subfolder : "" });
            }
        }
    }
    return items;
}

// Extensions can add action bar buttons since frontend 1.32.4.
export function hasActionBar(version) {
    const parts = String(version ?? "").split(".").map((part) => Number.parseInt(part, 10));
    if (parts.length < 3 || parts.some(Number.isNaN)) return false;
    for (const [index, minimum] of [1, 32, 4].entries()) {
        if (parts[index] !== minimum) return parts[index] > minimum;
    }
    return true;
}
