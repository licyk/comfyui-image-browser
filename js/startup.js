// ComfyUI middleware and reverse proxies may return plain text or an HTML error page.
export async function readStartupResponse(response, endpoint, messages) {
    const body = await response.text();
    let result;
    try {
        result = JSON.parse(body);
    } catch {
        // Report the failed request without embedding a proxy's HTML (or login form).
    }
    const record = result && typeof result === "object" && !Array.isArray(result) ? result : null;
    if (response.ok && record?.state === "ready") return;

    let hint = messages.server;
    if (response.status === 404 || response.status === 405) hint = messages.missing;
    else if (response.status === 401 || response.status === 403 || response.redirected) hint = messages.denied;
    else if (response.ok) hint = messages.unexpected;

    const detail = typeof record?.error === "string" ? record.error : "";
    const format = record ? "" : ` ${messages.notJson}`;
    throw new Error(`HTTP ${response.status} · ${endpoint}.${format} ${detail || hint}`);
}
