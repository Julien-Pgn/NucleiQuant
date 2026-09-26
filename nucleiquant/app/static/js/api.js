// Thin wrappers around the NucleiQuant HTTP API.

async function request(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { msg = (await res.json()).detail || msg; } catch (e) { /* not JSON */ }
    throw new Error(msg);
  }
  const type = res.headers.get("content-type") || "";
  return type.includes("application/json") ? res.json() : res.text();
}

export const get = (url) => request("GET", url);
export const post = (url, body = {}) => request("POST", url, body);
export const patch = (url, body = {}) => request("PATCH", url, body);
export const del = (url) => request("DELETE", url);

export async function binary(url) {
  const res = await fetch(url);
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  const shape = (res.headers.get("X-Shape") || "").split(",").filter(Boolean).map(Number);
  return { buffer: await res.arrayBuffer(), shape };
}

// Poll a background job until it finishes. onProgress(job) on every update.
export async function waitJob(job, onProgress) {
  let j = job;
  while (true) {
    if (onProgress) onProgress(j);
    if (j.status === "done") return j.result;
    if (j.status === "error") throw new Error(j.error || "Something went wrong");
    if (j.status === "cancelled") throw new Error("Cancelled");
    await new Promise((r) => setTimeout(r, 450));
    j = await get(`/api/jobs/${j.id}`);
  }
}

export function parseOutlines(buffer) {
  const head = new Uint32Array(buffer, 0, 2);
  const n = head[0];
  const m = head[1];
  let off = 8;
  const ids = new Uint32Array(buffer, off, n); off += 4 * n;
  const offsets = new Uint32Array(buffer, off, n + 1); off += 4 * (n + 1);
  const pts = new Uint16Array(buffer.slice(off, off + 4 * m));
  return { ids, offsets, pts };
}
