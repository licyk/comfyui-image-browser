import assert from "node:assert/strict";
import test from "node:test";
import { canOpenWorkflow, inputValue, isBridgeMessage, sendRequest, TARGETS } from "../js/host.js";

test("offers Open workflow for ComfyUI and WebUI images and Load Image for any image", () => {
    assert.deepEqual(TARGETS.map((t) => t.id), ["workflow", "loadImage"]);
    assert.deepEqual(TARGETS[0].platforms, ["comfyui", "sd-webui"]);
    assert.equal(TARGETS[1].platforms, undefined);
});

test("recognises only Hanaikada's protocol v1", () => {
    assert.ok(isBridgeMessage({ ns: "hanaikada", v: 1, type: "hello" }));
    assert.ok(!isBridgeMessage({ ns: "hanaikada", v: 2, type: "hello" }));
    assert.ok(!isBridgeMessage({ ns: "other", v: 1, type: "hello" }));
    assert.ok(!isBridgeMessage(null));
    assert.ok(!isBridgeMessage("hello"));
});

for (const [name, platform, expected] of [
    ["ComfyUI_00001_.png", "comfyui", true], ["clip.WEBP", "comfyui", true], ["x.avif", "comfyui", true],
    ["x.jpg", "comfyui", false], ["00001.png", "sd-webui", true], ["00001.jpg", "sd-webui", false],
    ["00001.webp", "sd-webui", false], ["a.png", "invokeai", false], ["a.png", null, false],
]) {
    test(`workflow from ${name} (${platform}): ${expected}`, () => assert.equal(canOpenWorkflow(name, platform), expected));
}

test("a file in ComfyUI's input folder is chosen as it is, anything else is uploaded", () => {
    assert.equal(inputValue({ root_id: "comfyui-input", path: "masks/a.png" }), "masks/a.png");
    assert.equal(inputValue({ root_id: "comfyui-input", path: "masks\\a.png" }), "masks/a.png");
    assert.equal(inputValue({ root_id: "comfyui-output", path: "a.png" }), null);
    assert.equal(inputValue({ root_id: "comfyui-input", path: "" }), null);
    assert.equal(inputValue(undefined), null);
});

test("accepts only well-formed send requests", () => {
    const item = { root_id: "comfyui-output", path: "a.png", name: "a.png", url: "/image-browser/api/v1/x" };
    assert.deepEqual(sendRequest({ ns: "hanaikada", v: 1, type: "send", id: "1", target: "workflow", payload: { item, platform: "comfyui" } }), {
        id: "1", target: "workflow", item, platform: "comfyui",
    });
    assert.equal(sendRequest({ ns: "hanaikada", v: 1, type: "send", id: "1", target: "workflow", payload: {} }), null);
    assert.equal(sendRequest({ ns: "hanaikada", v: 1, type: "hello" }), null);
});
