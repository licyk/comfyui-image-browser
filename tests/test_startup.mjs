import assert from "node:assert/strict";
import test from "node:test";
import { readStartupResponse } from "../js/startup.js";

const endpoint = "/comfy/api/image-browser-extension/start";
const messages = {
    notJson: "Not JSON", missing: "Restart ComfyUI", denied: "Check authentication and public URL",
    unexpected: "Check proxy routes", server: "Check backend log",
};

test("accepts the actual startup response", async () => {
    await readStartupResponse(Response.json({ state: "ready", error: null }), endpoint, messages);
});

for (const [status, body, hint] of [
    [403, "Cross-origin image browser request refused", messages.denied],
    [404, "404: Not Found", messages.missing],
    [405, "405: Method Not Allowed", messages.missing],
    [502, "<html><body>Bad gateway</body></html>", messages.server],
    [200, "<!doctype html><html>ComfyUI frontend</html>", messages.unexpected],
    [200, "", messages.unexpected],
    [200, "null", messages.unexpected],
]) {
    test(`reports actionable errors for ${status} with body ${JSON.stringify(body)}`, async () => {
        await assert.rejects(readStartupResponse(new Response(body, { status }), endpoint, messages), error => {
            assert.match(error.message, new RegExp(`HTTP ${status}`));
            assert.ok(error.message.includes(endpoint));
            assert.ok(error.message.includes(hint));
            assert.ok(!error.message.includes("<html>"));
            assert.ok(!(error instanceof SyntaxError));
            return true;
        });
    });
}

test("preserves the backend's startup failure", async () => {
    const response = Response.json({ state: "failed", error: "Hanaikada's web UI is missing" }, { status: 503 });
    await assert.rejects(readStartupResponse(response, endpoint, messages), /HTTP 503.*web UI is missing/);
});

test("identifies a successful HTML login redirect as authentication failure", async () => {
    const response = new Response("<html>Login</html>");
    Object.defineProperty(response, "redirected", { value: true });
    await assert.rejects(readStartupResponse(response, endpoint, messages), /Check authentication and public URL/);
});
