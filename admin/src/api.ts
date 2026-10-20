export const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const KEY = "chargeshare.admin.token";

export const getToken = () => localStorage.getItem(KEY);
export const setToken = (t: string | null) => (t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY));

export async function api<T = unknown>(path: string, body?: unknown, method?: string): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${API_URL}${path}`, {
    method: method ?? (body !== undefined ? "POST" : "GET"),
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    if (res.status === 401) setToken(null);
    const d = data?.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d[0]?.msg : `Error ${res.status}`);
  }
  return data as T;
}

/** Private files (ID documents) need the auth header, so fetch them as a blob and open in a new tab. */
export async function openPrivateFile(key: string) {
  const res = await fetch(`${API_URL}/admin/files/${key}`, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!res.ok) return alert("Couldn't open file");
  const url = URL.createObjectURL(await res.blob());
  window.open(url, "_blank");
}

export const rupees = (paise: number | null | undefined) =>
  `₹${((paise ?? 0) / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

export const when = (s: string | null | undefined) =>
  s ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z").toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—";
