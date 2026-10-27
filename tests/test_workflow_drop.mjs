import assert from "node:assert/strict";
import test from "node:test";
import { readRefs, REFS, toItems } from "../js/drop_payload.js";

// Stands in for the DataTransfer of a drop event.
function transfer(data) {
    return { getData: (type) => data[type] ?? "" };
}

test("reads the refs Hanaikada sets for a drag", () => {
    const refs = [{ root_id: "comfyui-output", path: "a.png" }, { root_id: "comfyui-input", path: "masks/b.png" }];
    assert.deepEqual(readRefs(transfer({ [REFS]: JSON.stringify(refs) })), refs);
});

test("ignores refs without a location and falls back to the text form", () => {
    const json = JSON.stringify([{ root_id: "comfyui-output" }, { path: "b.png" }, null]);
    assert.deepEqual(readRefs(transfer({ [REFS]: json, "text/plain": "comfyui-output:a.png" })), [
        { root_id: "comfyui-output", path: "a.png" },
    ]);
});

test("reads the plain text form when the JSON one is unusable", () => {
    assert.deepEqual(readRefs(transfer({ [REFS]: "not json", "text/plain": "comfyui-output:a.png comfyui-output:b.png" })), [
        { root_id: "comfyui-output", path: "a.png" },
        { root_id: "comfyui-output", path: "b.png" },
    ]);
    assert.deepEqual(readRefs(transfer({ "text/plain": "  " })), []);
    assert.deepEqual(readRefs(transfer({})), []);
});

test("drops text pairs that are not root_id:path", () => {
    assert.deepEqual(readRefs(transfer({ "text/plain": "nocolon :empty comfyui-output:a.png" })), [
        { root_id: "comfyui-output", path: "a.png" },
    ]);
});

test("turns the workflow file's link arrays into the objects the paste path reads", () => {
    const items = toItems({
        nodes: [{ id: 1, type: "KSampler", pos: [0, 0] }],
        links: [[1, 2, 0, 1, 0, "MODEL"]],
        groups: [{ title: "g", bounding: [0, 0, 10, 10] }],
    });
    assert.deepEqual(items.links, [{ id: 1, origin_id: 2, origin_slot: 0, target_id: 1, target_slot: 0, type: "MODEL" }]);
    assert.equal(items.nodes.length, 1);
    assert.equal(items.groups[0].title, "g");
    assert.deepEqual(items.reroutes, []);
    assert.deepEqual(items.subgraphs, []);
});

test("keeps links that already are objects and reads subgraphs from the workflow's definitions", () => {
    const link = { id: 3, origin_id: 1, origin_slot: 1, target_id: 2, target_slot: 0, parentId: 9 };
    const subgraphs = [{ id: "s1" }];
    const items = toItems({ links: [link], definitions: { subgraphs } });
    assert.equal(items.links[0], link);
    assert.equal(items.subgraphs, subgraphs);
    assert.deepEqual(items.nodes, []);
    assert.deepEqual(items.groups, []);
});
