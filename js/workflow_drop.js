// Drag a picture from Hanaikada onto the canvas: the workflow saved inside that picture is
// inserted into the workflow that is already open, instead of replacing it. Hanaikada already
// starts the drag itself and puts the file's location in the data transfer, so a drop only has
// to resolve that location to the workflow ComfyUI wrote next to the pixels.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { readRefs, REFS, toItems } from "./drop_payload.js";

const CLIPBOARD_KEY = "litegrapheditor_clipboard";

function imagesApi() {
    // Hanaikada answers behind the extension's own proxy route, on this origin.
    return api.fileURL("/image-browser/api/v1/images");
}

async function fetchJson(url) {
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

async function readWorkflow(ref, strings) {
    const base = imagesApi();
    const query = new URLSearchParams({ root_id: ref.root_id, path: ref.path });
    const detail = await fetchJson(`${base}/by-path?${query}`);
    const id = detail?.record?.id;
    if (id == null) throw new Error(ref.path);
    // Pictures from other tools keep no workflow, only the prompt that made them.
    if (!(detail.chunks ?? []).includes("workflow")) throw new Error(strings.noWorkflow);
    return fetchJson(`${base}/${id}/raw/workflow`);
}

// Inserts with fresh node and link ids, at `position`, and leaves the open workflow's nodes be.
export function insert(workflow, position, strings, canvas = app.canvas) {
    const items = toItems(workflow);
    if (!items.nodes.length) throw new Error(strings.noWorkflow);
    if (typeof canvas._deserializeItems === "function") {
        canvas._deserializeItems(items, { position });
    } else if (typeof canvas.pasteFromClipboard === "function") {
        // Frontends that only paste from the canvas clipboard; the user's stays as it was.
        const previous = localStorage.getItem(CLIPBOARD_KEY);
        localStorage.setItem(CLIPBOARD_KEY, JSON.stringify(items));
        try {
            canvas.pasteFromClipboard({ position });
        } finally {
            if (previous === null) localStorage.removeItem(CLIPBOARD_KEY);
            else localStorage.setItem(CLIPBOARD_KEY, previous);
        }
    } else {
        throw new Error(strings.unsupported);
    }
    canvas.setDirty?.(true, true);
}

function dropPosition(event, canvas = app.canvas) {
    const box = canvas.canvas.getBoundingClientRect();
    return canvas.ds.convertCanvasToOffset([event.clientX - box.left, event.clientY - box.top]);
}

function notify(message) {
    const toast = document.createElement("div");
    toast.className = "comfy-image-browser-toast";
    toast.setAttribute("role", "status");
    toast.textContent = message;
    document.body.append(toast);
    setTimeout(() => toast.remove(), 6000);
}

export function installWorkflowDrop(text) {
    const carriesImage = (event) => Boolean(event.dataTransfer)
        && Array.from(event.dataTransfer.types).includes(REFS);

    document.addEventListener("dragover", (event) => {
        if (!carriesImage(event)) return;
        // Claim the drop, so ComfyUI does not try to read the picture as a workflow file.
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
    }, true);

    document.addEventListener("drop", (event) => {
        if (!carriesImage(event)) return;
        event.preventDefault();
        event.stopPropagation();
        const refs = readRefs(event.dataTransfer);
        if (!refs.length) return;
        const position = dropPosition(event);
        void (async () => {
            const strings = text();
            try {
                const workflow = await readWorkflow(refs[0], strings);
                insert(workflow, position, strings);
                if (refs.length > 1) notify(strings.firstOnly);
            } catch (error) {
                notify(`${strings.failed} ${error?.message || error}`);
            }
        })();
    }, true);
}
