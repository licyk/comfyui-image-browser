import assert from "node:assert/strict";
import test from "node:test";
import { hasActionBar, resultItems } from "../js/frontend.js";

test("collects saved results under any output key", () => {
    const output = {
        images: [
            { filename: "a.png", subfolder: "day", type: "output" },
            { filename: "preview.png", subfolder: "", type: "temp" },
            { filename: "mask.png", type: "input" },
        ],
        gifs: [{ filename: "clip.webp", subfolder: "", type: "output", format: "image/webp" }],
        text: ["not a result"],
        animated: [true],
    };
    assert.deepEqual(resultItems(output), [
        { type: "output", subfolder: "day" },
        { type: "input", subfolder: "" },
        { type: "output", subfolder: "" },
    ]);
    assert.deepEqual(resultItems(undefined), []);
    assert.deepEqual(resultItems({ images: [null, { subfolder: "x", type: "output" }] }), []);
});

for (const [version, expected] of [
    ["1.53.6", true], ["1.32.4", true], ["2.0.0", true], ["1.32.3", false], ["1.31.9", false],
    ["0.99.0", false], [undefined, false], ["", false], ["1.x", false],
]) {
    test(`action bar support for ${version}`, () => assert.equal(hasActionBar(version), expected));
}
