import type { BookingStatus, Charger } from "./types";

export const rupees = (paise: number | null | undefined, decimals = 0) =>
  `₹${((paise ?? 0) / 100).toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;

export const priceLabel = (c: Pick<Charger, "price_paise" | "pricing_mode">) =>
  `${rupees(c.price_paise, c.price_paise % 100 ? 2 : 0)}/${c.pricing_mode === "kwh" ? "kWh" : "hr"}`;

/** Server sends naive UTC timestamps ("2026-10-20T08:00:00"); treat them as UTC. */
export const parseUtc = (s: string) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");

const DAY = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short" });
const TIME = new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit", hour12: true });

export const dayLabel = (d: Date) => {
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === tomorrow.toDateString()) return "Tomorrow";
  return DAY.format(d);
};
export const timeLabel = (d: Date) => TIME.format(d);
export const slotLabel = (startIso: string, endIso: string) => {
  const s = parseUtc(startIso);
  const e = parseUtc(endIso);
  return `${dayLabel(s)}, ${timeLabel(s)} – ${timeLabel(e)}`;
};

export const durationLabel = (minutes: number) => {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h && m ? `${h}h ${m}m` : h ? `${h} hr${h > 1 ? "s" : ""}` : `${m} min`;
};

export const hoursLabel = (open: string, close: string) => (open === close ? "Open 24 hours" : `${open} – ${close}`);

export const STATUS_TEXT: Record<BookingStatus, { label: string; tone: "green" | "amber" | "red" | "blue" | "grey" }> = {
  pending_payment: { label: "Payment pending", tone: "amber" },
  requested: { label: "Waiting for host", tone: "amber" },
  confirmed: { label: "Confirmed", tone: "green" },
  active: { label: "Charging", tone: "blue" },
  completed: { label: "Completed", tone: "grey" },
  cancelled: { label: "Cancelled", tone: "red" },
  declined: { label: "Declined", tone: "red" },
  expired: { label: "Expired", tone: "grey" },
};
