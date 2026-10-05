"use client";

const BASE = (process.env.NEXT_PUBLIC_API_URL || "") + "/api";
const TOKEN_KEY = "vkreger_token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

function detailToText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`)
      .join("; ");
  return JSON.stringify(detail);
}

export async function api<T = unknown>(path: string, options: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = options.body;
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  }
  const response = await fetch(BASE + path, { ...options, headers, body });
  if (response.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/login")) {
    setToken(null);
    window.location.href = "/login";
    throw new ApiError(401, "Требуется вход");
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : undefined;
  if (!response.ok) {
    const message = data && typeof data === "object" && "detail" in data ? detailToText(data.detail) : String(data || response.statusText);
    throw new ApiError(response.status, message);
  }
  return data as T;
}

export async function login(email: string, password: string): Promise<void> {
  const form = new URLSearchParams({ username: email, password });
  const data = await api<{ access_token: string }>("/auth/login", {
    method: "POST",
    body: form,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  setToken(data.access_token);
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return entries.length ? "?" + new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString() : "";
}

/** Download a file from the API with the auth header and save it in the browser. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const token = getToken();
  const response = await fetch(BASE + path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!response.ok) throw new ApiError(response.status, `Не удалось скачать файл (HTTP ${response.status})`);
  const name = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") || "")?.[1] || fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
