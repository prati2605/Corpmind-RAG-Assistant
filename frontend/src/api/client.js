/**
 * API client.
 *
 * - The access token lives only in memory (a module variable), never in localStorage.
 * - The refresh token lives in an httpOnly cookie set by the backend; JavaScript can't read it.
 * - On a 401, the client calls /auth/refresh once (shared across concurrent requests), then retries.
 */
const BASE = "/api/v1";

let accessToken = null;
let refreshing = null;
let onAuthLost = () => {};

export function setAccessToken(token) {
  accessToken = token;
}
export function setOnAuthLost(fn) {
  onAuthLost = fn;
}

export class ApiError extends Error {
  constructor(status, detail, errors) {
    super(typeof detail === "string" ? detail : detail?.message || "Request failed");
    this.status = status;
    this.detail = detail;
    this.errors = errors || [];
  }
}

export async function refreshSession() {
  if (!refreshing) {
    refreshing = fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) throw new ApiError(r.status, "Session expired");
        const data = await r.json();
        accessToken = data.access_token;
        return data;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

async function parseError(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error */
  }
  const fallback = {
    413: "That file is too large.",
    429: "Too many requests. Wait a moment and try again.",
    500: "Something went wrong on the server. Try again.",
    503: "The service is temporarily unavailable. Try again shortly.",
  }[res.status];
  return new ApiError(res.status, body?.detail ?? fallback ?? `Request failed (${res.status})`, body?.errors);
}

export async function api(path, { method = "GET", body, form, query, raw = false, retry = true } = {}) {
  const url = new URL(BASE + path, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === "") continue;
      if (Array.isArray(v)) v.forEach((x) => url.searchParams.append(k, x));
      else url.searchParams.set(k, v);
    }
  }
  const headers = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });

  if (res.status === 401 && retry && !path.startsWith("/auth/")) {
    try {
      await refreshSession();
    } catch {
      onAuthLost();
      throw new ApiError(401, "Your session has ended. Sign in again.");
    }
    return api(path, { method, body, form, query, raw, retry: false });
  }
  if (!res.ok) throw await parseError(res);
  if (raw) return res;
  if (res.status === 204) return null;
  return res.json();
}

/** Download a protected file (needs the Authorization header, so a plain link won't do). */
export async function downloadFile(path, fallbackName) {
  const res = await api(path, { raw: true });
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const name = match ? decodeURIComponent(match[1]) : fallbackName;
  const href = URL.createObjectURL(blob);
  if (blob.type === "application/pdf") {
    window.open(href, "_blank", "noopener");
  } else {
    const a = Object.assign(document.createElement("a"), { href, download: name });
    a.click();
  }
  setTimeout(() => URL.revokeObjectURL(href), 60_000);
}
