import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Alert, View } from "react-native";

import { api } from "../../src/api";
import { useAuth } from "../../src/auth";
import { dayLabel, durationLabel, parseUtc, priceLabel, rupees, timeLabel } from "../../src/format";
import { space } from "../../src/theme";
import type { ChargerDetail, Checkout } from "../../src/types";
import { Body, Button, Card, Chip, ChipGroup, Empty, Field, H2, Loading, Notice, Row, Screen, Small, useLoad } from "../../src/ui";

const DURATIONS = [30, 60, 90, 120, 180, 240, 360, 480];

const toMinutes = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

/** true if minute-of-day `t` is inside the open window (handles overnight windows and 24h). */
function inWindow(t: number, open: number, close: number) {
  if (open === close) return true;
  if (open < close) return t >= open && t < close;
  return t >= open || t < close;
}

function fits(start: Date, minutes: number, open: number, close: number, busy: { s: Date; e: Date }[]) {
  const end = new Date(start.getTime() + minutes * 60000);
  for (let t = start.getTime(); t < end.getTime(); t += 5 * 60000) {
    const d = new Date(t);
    if (!inWindow(d.getHours() * 60 + d.getMinutes(), open, close)) return false;
  }
  return !busy.some((b) => b.s < end && b.e > start);
}

export default function Book() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const { data: c, loading } = useLoad(() => api<ChargerDetail>(`/chargers/${id}`), [id]);

  const days = useMemo(() => {
    const out: Date[] = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date();
      d.setHours(0, 0, 0, 0);
      d.setDate(d.getDate() + i);
      out.push(d);
    }
    return out;
  }, []);
  const [dayIdx, setDayIdx] = useState(0);
  const [start, setStart] = useState<Date | null>(null);
  const [duration, setDuration] = useState(60);
  const [vehicle, setVehicle] = useState<string>(user?.vehicle_type ?? "");
  const [note, setNote] = useState("");
  const [quote, setQuote] = useState<{ amount_paise: number; note: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const busySlots = useMemo(() => (c?.busy ?? []).map((b) => ({ s: parseUtc(b.start_at), e: parseUtc(b.end_at) })), [c]);
  const open = c ? toMinutes(c.open_time) : 0;
  const close = c ? toMinutes(c.close_time) : 0;

  const startOptions = useMemo(() => {
    if (!c) return [];
    const now = Date.now() + 5 * 60000;
    const out: Date[] = [];
    for (let m = 0; m < 24 * 60; m += 30) {
      const d = new Date(days[dayIdx]);
      d.setMinutes(m);
      if (d.getTime() < now) continue;
      if (fits(d, 30, open, close, busySlots)) out.push(d);
    }
    return out;
  }, [c, dayIdx, days, open, close, busySlots]);

  const durationOptions = useMemo(
    () => (start ? DURATIONS.filter((m) => fits(start, m, open, close, busySlots)) : DURATIONS),
    [start, open, close, busySlots],
  );

  useEffect(() => setStart(null), [dayIdx]);
  useEffect(() => {
    if (start && !durationOptions.includes(duration)) setDuration(durationOptions[0] ?? 30);
  }, [start, durationOptions, duration]);

  useEffect(() => {
    if (!c || !start) return setQuote(null);
    const end = new Date(start.getTime() + duration * 60000);
    api<{ amount_paise: number; note: string }>("/bookings/quote", {
      body: { charger_id: c.id, start_at: start.toISOString(), end_at: end.toISOString() },
    })
      .then(setQuote)
      .catch(() => setQuote(null));
  }, [c, start, duration]);

  if (loading && !c) return <Loading />;
  if (!c) return <Empty title="Charger not found" />;

  async function confirm() {
    if (!c || !start) return;
    setBusy(true);
    try {
      const end = new Date(start.getTime() + duration * 60000);
      const res = await api<Checkout>("/bookings", {
        body: { charger_id: c.id, start_at: start.toISOString(), end_at: end.toISOString(), vehicle_type: vehicle, vehicle_note: note },
      });
      router.replace({
        pathname: "/pay",
        params: { bookingId: String(res.booking.id), provider: res.provider, url: res.checkout_url, amount: String(res.booking.amount_paise) },
      });
    } catch (e) {
      Alert.alert("Couldn't book", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const vehicleOptions = c.vehicle_types.map((v) => ({ value: v, label: v === "2W" ? "Scooter / bike" : v === "3W" ? "Auto" : "Car" }));

  return (
    <Screen>
      <Card>
        <H2>{c.title}</H2>
        <Small>
          {priceLabel(c)} · {c.connector_type} · {c.power_kw} kW
        </Small>
      </Card>

      <H2>Day</H2>
      <Row style={{ flexWrap: "wrap" }}>
        {days.map((d, i) => (
          <Chip key={d.toISOString()} label={dayLabel(d)} selected={i === dayIdx} onPress={() => setDayIdx(i)} />
        ))}
      </Row>

      <H2>Start time</H2>
      {startOptions.length === 0 ? (
        <Small>No free slots on this day. Try another day.</Small>
      ) : (
        <Row style={{ flexWrap: "wrap" }}>
          {startOptions.map((d) => (
            <Chip key={d.toISOString()} label={timeLabel(d)} selected={start?.getTime() === d.getTime()} onPress={() => setStart(d)} />
          ))}
        </Row>
      )}

      <H2>How long?</H2>
      <Row style={{ flexWrap: "wrap" }}>
        {durationOptions.map((m) => (
          <Chip key={m} label={durationLabel(m)} selected={duration === m} onPress={() => setDuration(m)} />
        ))}
      </Row>

      {vehicleOptions.length > 1 && (
        <>
          <H2>Your vehicle</H2>
          <ChipGroup options={vehicleOptions} value={vehicle} onChange={(v) => setVehicle(v as string)} />
        </>
      )}
      <Field label="Vehicle details (optional)" value={note} onChangeText={setNote} placeholder="e.g. Nexon EV, white, TS09 AB 1234" maxLength={120} />

      {start && quote && (
        <Card>
          <Row style={{ justifyContent: "space-between" }}>
            <Body>
              {dayLabel(start)}, {timeLabel(start)} – {timeLabel(new Date(start.getTime() + duration * 60000))}
            </Body>
          </Row>
          <Row style={{ justifyContent: "space-between" }}>
            <H2>Total</H2>
            <H2>{rupees(quote.amount_paise, 2)}</H2>
          </Row>
          <Small>{quote.note}</Small>
        </Card>
      )}
      <Notice text="Free cancellation up to 1 hour before your slot. Later cancellations get a 50% refund." />
      <View style={{ height: space.sm }} />
      <Button title={quote ? `Pay ${rupees(quote.amount_paise)} and book` : "Choose a time"} onPress={confirm} loading={busy} disabled={!start || !quote} />
    </Screen>
  );
}
