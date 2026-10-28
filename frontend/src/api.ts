export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export const sessionKey = "acquisitions-session";
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = sessionStorage.getItem(sessionKey);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch("/api" + path, { ...init, headers });
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({
        detail: "The local server could not complete this request.",
      }));
    if (response.status === 401 && !path.startsWith("/auth/"))
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(
      typeof data.detail === "string"
        ? data.detail
        : "Check the request and try again.",
      response.status,
    );
  }
  return response.json() as Promise<T>;
}
export function post<T>(path: string, body: unknown = {}) {
  return api<T>(path, { method: "POST", body: JSON.stringify(body) });
}
export function patch<T>(path: string, body: unknown) {
  return api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}
export function del<T>(path: string) {
  return api<T>(path, { method: "DELETE" });
}
export async function download(path: string, filename: string) {
  const headers: Record<string, string> = {};
  const token = sessionStorage.getItem(sessionKey);
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch("/api" + path, { headers });
  if (!res.ok) {
    const d = await res.json();
    throw new Error(d.detail || "Export failed");
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  // Revoking immediately cancels the download in Safari; give the click a moment.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
export const human = (s: string) =>
  s.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
export function dateTime(
  value: string | null | undefined,
  zone?: string,
  dateOnly = false,
) {
  if (!value) return "Not recorded";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "Invalid source date";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    ...(dateOnly ? {} : { hour: "numeric", minute: "2-digit" }),
    timeZone: zone,
  }).format(d);
}
export const currency = (n: number | null | undefined) =>
  n == null
    ? "Not recorded"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(n);
export function isoFromLocal(value: string) {
  return value ? new Date(value).toISOString() : null;
}
