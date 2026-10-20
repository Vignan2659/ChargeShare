import { useCallback, useEffect, useState, type ReactNode } from "react";

import { api, getToken, openPrivateFile, rupees, setToken, when } from "./api";

// ---------- types (subset of the API) ----------
type User = {
  id: number; phone: string; name: string; email: string; is_admin: boolean; is_host: boolean;
  host_status: string; host_note: string; payout_upi: string; id_doc_keys: string[]; created_at: string; deleted_at: string | null;
};
type Charger = {
  id: number; host_id: number; host_name: string; title: string; address: string; lat: number; lng: number;
  vehicle_types: string[]; connector_type: string; power_kw: number; pricing_mode: string; price_paise: number;
  photo_urls: string[]; open_time: string; close_time: string; status: string; safety_checked: boolean;
  has_society_noc: boolean; society_only: boolean; society_name: string; admin_note: string; created_at: string;
  description: string; rating_avg: number | null; rating_count: number;
};
type Booking = {
  id: number; driver_id: number; host_id: number; status: string; start_at: string; end_at: string;
  amount_paise: number; final_amount_paise: number | null; refund_paise: number; commission_paise: number;
  host_earning_paise: number; cancel_reason: string; cancelled_by: string; created_at: string; no_show: boolean;
  charger: { id: number; title: string }; other_party_name: string;
};
type Report = { id: number; reporter_id: number; booking_id: number | null; charger_id: number | null; category: string; message: string; status: string; admin_reply: string; created_at: string };
type Payout = { id: number; host_id: number; host_name: string; host_phone: string; amount_paise: number; booking_count: number; upi_id: string; status: string; reference: string; created_at: string; paid_at: string | null };
type Stats = Record<string, number>;

const TABS = ["Dashboard", "Hosts", "Chargers", "Bookings", "Reports", "Payouts"] as const;
type Tab = (typeof TABS)[number];

// ---------- small helpers ----------
function useData<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    loader().then(setData).catch((e: Error) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(reload, [reload]);
  return { data, error, reload };
}

async function run(action: () => Promise<unknown>, after: () => void) {
  try {
    await action();
    after();
  } catch (e) {
    alert((e as Error).message);
  }
}

const Pill = ({ s }: { s: string }) => <span className={`pill pill-${s}`}>{s.replace("_", " ")}</span>;
const Section = ({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) => (
  <section>
    <div className="section-head">
      <h2>{title}</h2>
      {right}
    </div>
    {children}
  </section>
);
function Filter({ value, options, onChange }: { value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => (
        <option key={o} value={o}>
          {o || "all"}
        </option>
      ))}
    </select>
  );
}

// ---------- login ----------
function Login({ onDone }: { onDone: () => void }) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [err, setErr] = useState("");

  async function send() {
    setErr("");
    try {
      const r = await api<{ phone: string }>("/auth/otp/request", { phone });
      setSent(r.phone);
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  async function verify() {
    setErr("");
    try {
      const r = await api<{ token: string; user: User }>("/auth/otp/verify", { phone: sent, code });
      if (!r.user.is_admin) return setErr("This number is not an admin. Add it to ADMIN_PHONES on the server.");
      setToken(r.token);
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  return (
    <div className="login">
      <h1>⚡ ChargeShare Admin</h1>
      {!sent ? (
        <>
          <input placeholder="Admin mobile number" value={phone} onChange={(e) => setPhone(e.target.value)} />
          <button onClick={send}>Send OTP</button>
        </>
      ) : (
        <>
          <p>OTP sent to {sent}</p>
          <input placeholder="6-digit OTP" value={code} onChange={(e) => setCode(e.target.value)} />
          <button onClick={verify}>Log in</button>
        </>
      )}
      {err && <p className="error">{err}</p>}
    </div>
  );
}

// ---------- pages ----------
function Dashboard() {
  const { data: s } = useData(() => api<Stats>("/admin/stats"), []);
  if (!s) return <p>Loading…</p>;
  const tiles: [string, string][] = [
    ["Users", String(s.users)],
    ["Verified hosts", String(s.hosts_approved)],
    ["Hosts waiting", String(s.hosts_pending)],
    ["Live chargers", String(s.chargers_live)],
    ["Chargers waiting", String(s.chargers_pending)],
    ["Open bookings", String(s.bookings_open)],
    ["Completed bookings", String(s.bookings_completed)],
    ["Paid bookings (7 days)", String(s.bookings_last_7_days)],
    ["Gross bookings", rupees(s.gross_paise)],
    ["Commission earned", rupees(s.commission_paise)],
    ["Payouts to send", rupees(s.payouts_pending_paise)],
    ["Open reports", String(s.reports_open)],
  ];
  return (
    <div className="tiles">
      {tiles.map(([k, v]) => (
        <div className="tile" key={k}>
          <div className="tile-label">{k}</div>
          <div className="tile-value">{v}</div>
        </div>
      ))}
    </div>
  );
}

function Hosts() {
  const [status, setStatus] = useState("pending");
  const [q, setQ] = useState("");
  const { data, reload, error } = useData(
    () => {
      const qs = new URLSearchParams();
      if (status) qs.set("host_status", status);
      if (q) qs.set("q", q);
      return api<User[]>(`/admin/users?${qs}`);
    },
    [status, q],
  );
  return (
    <Section
      title="Users and hosts"
      right={
        <div className="row">
          <input placeholder="Search phone / name" value={q} onChange={(e) => setQ(e.target.value)} />
          <Filter value={status} options={["pending", "approved", "rejected", "none", ""]} onChange={setStatus} />
        </div>
      }
    >
      {error && <p className="error">{error}</p>}
      <table>
        <thead>
          <tr><th>Name</th><th>Phone</th><th>Host status</th><th>UPI</th><th>ID proof</th><th>Joined</th><th /></tr>
        </thead>
        <tbody>
          {data?.map((u) => (
            <tr key={u.id}>
              <td>{u.name || "—"} {u.is_admin && <Pill s="admin" />}</td>
              <td>{u.phone}</td>
              <td><Pill s={u.host_status} />{u.host_note && <div className="muted">{u.host_note}</div>}</td>
              <td>{u.payout_upi || "—"}</td>
              <td>
                {u.id_doc_keys.map((k, i) => (
                  <button key={k} className="link" onClick={() => openPrivateFile(k)}>Doc {i + 1}</button>
                ))}
              </td>
              <td>{when(u.created_at)}</td>
              <td className="actions">
                {u.host_status !== "approved" && u.host_status !== "none" && (
                  <button onClick={() => run(() => api(`/admin/hosts/${u.id}/approve`, {}), reload)}>Approve</button>
                )}
                {u.host_status !== "rejected" && u.host_status !== "none" && (
                  <button className="danger" onClick={() => {
                    const note = prompt("Reason (shown to the user)", "ID photo is not clear. Please upload again.");
                    if (note !== null) void run(() => api(`/admin/hosts/${u.id}/reject`, { note }), reload);
                  }}>Reject</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

function Chargers() {
  const [status, setStatus] = useState("pending");
  const { data, reload } = useData(() => api<Charger[]>(`/admin/chargers${status ? `?status=${status}` : ""}`), [status]);
  return (
    <Section title="Chargers" right={<Filter value={status} options={["pending", "approved", "rejected", "paused", "removed", ""]} onChange={setStatus} />}>
      <div className="cards">
        {data?.length === 0 && <p className="muted">Nothing here.</p>}
        {data?.map((c) => (
          <div className="card" key={c.id}>
            <div className="photos">
              {c.photo_urls.map((u) => <a key={u} href={u} target="_blank" rel="noreferrer"><img src={u} alt="" /></a>)}
              {c.photo_urls.length === 0 && <div className="muted">No photos</div>}
            </div>
            <h3>{c.title} <Pill s={c.status} /></h3>
            <div className="muted">#{c.id} · host {c.host_name} (user {c.host_id}) · {when(c.created_at)}</div>
            <p>{c.address} · <a href={`https://maps.google.com/?q=${c.lat},${c.lng}`} target="_blank" rel="noreferrer">map</a></p>
            <p>{c.connector_type} · {c.power_kw} kW · {c.vehicle_types.join(", ")} · {rupees(c.price_paise)}/{c.pricing_mode === "kwh" ? "kWh" : "hr"} · {c.open_time === c.close_time ? "24h" : `${c.open_time}–${c.close_time}`}</p>
            <p>
              Society NOC: <b>{c.has_society_noc ? "yes" : "no"}</b>
              {c.society_only && <> · residents only ({c.society_name || "unnamed"})</>}
              {c.safety_checked && <> · safety checked</>}
            </p>
            {c.description && <p className="muted">{c.description}</p>}
            {c.admin_note && <p className="muted">Note: {c.admin_note}</p>}
            <div className="actions">
              {c.status !== "approved" && c.status !== "removed" && (
                <button onClick={() => {
                  const safety = confirm("Mark as SAFETY CHECKED? (OK = yes, Cancel = approve without the badge)");
                  void run(() => api(`/admin/chargers/${c.id}/approve`, { safety_checked: safety }), reload);
                }}>Approve</button>
              )}
              {c.status !== "rejected" && c.status !== "removed" && (
                <button className="danger" onClick={() => {
                  const note = prompt("What should the host fix?", "Please add a clear photo of the charger and the parking spot.");
                  if (note !== null) void run(() => api(`/admin/chargers/${c.id}/reject`, { note }), reload);
                }}>Reject</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function Bookings() {
  const [status, setStatus] = useState("");
  const { data, reload } = useData(() => api<Booking[]>(`/admin/bookings${status ? `?status=${status}` : ""}`), [status]);
  return (
    <Section
      title="Bookings"
      right={<Filter value={status} options={["", "pending_payment", "requested", "confirmed", "active", "completed", "cancelled", "declined", "expired"]} onChange={setStatus} />}
    >
      <table>
        <thead>
          <tr><th>#</th><th>Charger</th><th>Slot</th><th>Status</th><th>Paid</th><th>Final</th><th>Refunded</th><th>Fee</th><th>Host gets</th><th /></tr>
        </thead>
        <tbody>
          {data?.map((b) => (
            <tr key={b.id}>
              <td>{b.id}</td>
              <td>{b.charger.title}<div className="muted">driver {b.driver_id} · host {b.host_id}</div></td>
              <td>{when(b.start_at)}<div className="muted">to {when(b.end_at)}</div></td>
              <td><Pill s={b.status} />{b.no_show && <div className="muted">no-show</div>}{b.cancel_reason && <div className="muted">{b.cancelled_by}: {b.cancel_reason}</div>}</td>
              <td>{rupees(b.amount_paise)}</td>
              <td>{b.final_amount_paise != null ? rupees(b.final_amount_paise) : "—"}</td>
              <td>{rupees(b.refund_paise)}</td>
              <td>{rupees(b.commission_paise)}</td>
              <td>{rupees(b.host_earning_paise)}</td>
              <td className="actions">
                {["pending_payment", "requested", "confirmed"].includes(b.status) && (
                  <button className="danger" onClick={() => {
                    const note = prompt("Cancel with FULL refund. Reason?", "");
                    if (note !== null) void run(() => api(`/admin/bookings/${b.id}/cancel`, { note }), reload);
                  }}>Cancel</button>
                )}
                {b.amount_paise - b.refund_paise > 0 && ["completed", "cancelled", "active", "confirmed"].includes(b.status) && (
                  <button onClick={() => {
                    const amt = prompt(`Refund how many ₹? (max ${(b.amount_paise - b.refund_paise) / 100})`);
                    if (!amt) return;
                    const reason = prompt("Reason", "") ?? "";
                    void run(() => api(`/admin/bookings/${b.id}/refund`, { amount_paise: Math.round(Number(amt) * 100), reason }), reload);
                  }}>Refund</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

function Reports() {
  const [status, setStatus] = useState("open");
  const { data, reload } = useData(() => api<Report[]>(`/admin/reports?status=${status}`), [status]);
  return (
    <Section title="Problem reports" right={<Filter value={status} options={["open", "resolved", ""]} onChange={setStatus} />}>
      <table>
        <thead><tr><th>When</th><th>Type</th><th>From user</th><th>About</th><th>Message</th><th /></tr></thead>
        <tbody>
          {data?.map((r) => (
            <tr key={r.id}>
              <td>{when(r.created_at)}</td>
              <td><Pill s={r.category} /></td>
              <td>{r.reporter_id}</td>
              <td>{r.booking_id ? `booking #${r.booking_id}` : r.charger_id ? `charger #${r.charger_id}` : "—"}</td>
              <td className="msg">{r.message}{r.admin_reply && <div className="muted">Reply: {r.admin_reply}</div>}</td>
              <td className="actions">
                {r.status === "open" && (
                  <button onClick={() => {
                    const reply = prompt("Reply to the user (sent as a notification)", "Thanks, we've sorted this out.");
                    if (reply !== null) void run(() => api(`/admin/reports/${r.id}/resolve`, { reply }), reload);
                  }}>Resolve</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

function Payouts() {
  const [status, setStatus] = useState("pending");
  const { data, reload } = useData(() => api<Payout[]>(`/admin/payouts${status ? `?status=${status}` : ""}`), [status]);
  return (
    <Section
      title="Host payouts"
      right={
        <div className="row">
          <Filter value={status} options={["pending", "paid", ""]} onChange={setStatus} />
          <button onClick={() => run(async () => {
            const made = await api<Payout[]>("/admin/payouts/generate", {});
            alert(made.length ? `Created ${made.length} payouts.` : "No new earnings to pay out.");
          }, reload)}>Create this week's payouts</button>
        </div>
      }
    >
      <p className="muted">Send each amount to the host's UPI ID from your business bank account, then mark it paid with the UTR/reference number.</p>
      <table>
        <thead><tr><th>#</th><th>Host</th><th>UPI ID</th><th>Sessions</th><th>Amount</th><th>Status</th><th>Created</th><th /></tr></thead>
        <tbody>
          {data?.map((p) => (
            <tr key={p.id}>
              <td>{p.id}</td>
              <td>{p.host_name}<div className="muted">{p.host_phone}</div></td>
              <td><code>{p.upi_id || "missing!"}</code></td>
              <td>{p.booking_count}</td>
              <td><b>{rupees(p.amount_paise)}</b></td>
              <td><Pill s={p.status} />{p.reference && <div className="muted">Ref {p.reference}</div>}</td>
              <td>{when(p.created_at)}</td>
              <td className="actions">
                {p.status === "pending" && (
                  <button onClick={() => {
                    const reference = prompt("UPI transaction reference (UTR)");
                    if (reference) void run(() => api(`/admin/payouts/${p.id}/mark-paid`, { reference }), reload);
                  }}>Mark paid</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

// ---------- shell ----------
export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [tab, setTab] = useState<Tab>("Dashboard");
  if (!authed) return <Login onDone={() => setAuthed(true)} />;
  const pages: Record<Tab, ReactNode> = {
    Dashboard: <Dashboard />, Hosts: <Hosts />, Chargers: <Chargers />, Bookings: <Bookings />, Reports: <Reports />, Payouts: <Payouts />,
  };
  return (
    <div className="shell">
      <nav>
        <div className="brand">⚡ ChargeShare</div>
        {TABS.map((t) => (
          <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
        <button className="logout" onClick={() => { setToken(null); setAuthed(false); }}>Log out</button>
      </nav>
      <main key={tab}>{pages[tab]}</main>
    </div>
  );
}
