// Reading the drag payload and turning the workflow ComfyUI saved into a picture into the shape
// the canvas paste path expects. Kept free of app imports so it can be tested on its own.

export const REFS = "application/x-hanaikada-refs";

// Hanaikada writes JSON refs and, beside them, "root_id:path" pairs as plain text. Both are
// readable only on drop, never while hovering.
export function readRefs(dataTransfer) {
    const json = dataTransfer.getData(REFS);
    if (json) {
        try {
            const refs = JSON.parse(json);
            if (Array.isArray(refs)) {
                const usable = refs.filter((ref) => ref?.root_id && ref?.path);
                if (usable.length) return usable;
            }
        } catch {
            // Fall through to the text form.
        }
    }
    const text = dataTransfer.getData("text/plain");
    if (!text) return [];
    return text.split(/\s+/).flatMap((pair) => {
        const at = pair.indexOf(":");
        return at > 0 ? [{ root_id: pair.slice(0, at), path: pair.slice(at + 1) }] : [];
    });
}

// The canvas' paste path takes nodes, groups and links in the shape the clipboard uses: links in
// the workflow file arrive as [id, origin, origin slot, target, target slot, type] arrays.
export function toItems(workflow) {
    const links = (workflow.links ?? []).map((link) => Array.isArray(link)
        ? {
            id: link[0], origin_id: link[1], origin_slot: link[2],
            target_id: link[3], target_slot: link[4], type: link[5],
        }
        : link);
    return {
        nodes: workflow.nodes ?? [],
        groups: workflow.groups ?? [],
        links,
        reroutes: workflow.reroutes ?? [],
        subgraphs: workflow.definitions?.subgraphs ?? workflow.subgraphs ?? [],
    };
}
