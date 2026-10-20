import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Alert, Linking, View } from "react-native";

import { api } from "../../src/api";
import { useAuth } from "../../src/auth";
import { durationLabel, parseUtc, rupees, slotLabel, STATUS_TEXT } from "../../src/format";
import { callNumber, openDirections } from "../../src/links";
import { space } from "../../src/theme";
import type { Booking, ExtraCheckout } from "../../src/types";
import { Badge, Body, Button, Card, Divider, Empty, Field, H2, InfoRow, Loading, Notice, Row, Screen, Small, useLoad } from "../../src/ui";

export default function BookingScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const { data: b, error, loading, reload, setData } = useLoad(() => api<Booking>(`/bookings/${id}`), [id]);
  const [busy, setBusy] = useState<string | null>(null);
  const [kwh, setKwh] = useState("");
  const [showBroken, setShowBroken] = useState(false);

  if (loading && !b) return <Loading />;
  if (!b) return <Empty title="Couldn't load booking" text={error ?? ""} />;

  const isDriver = b.driver_id === user?.id;
  const st = STATUS_TEXT[b.status];
  const minutes = Math.round((parseUtc(b.end_at).getTime() - parseUtc(b.start_at).getTime()) / 60000);
  const minutesToStart = (parseUtc(b.start_at).getTime() - Date.now()) / 60000;

  async function act(key: string, path: string, body: object = {}, confirmText?: string) {
    const run = async () => {
      setBusy(key);
      try {
        setData(await api<Booking>(path, { method: "POST", body }));
      } catch (e) {
        Alert.alert("Couldn't do that", (e as Error).message);
        void reload();
      } finally {
        setBusy(null);
      }
    };
    if (confirmText) {
      Alert.alert("Are you sure?", confirmText, [
        { text: "No", style: "cancel" },
        { text: "Yes", style: "destructive", onPress: () => void run() },
      ]);
    } else {
      await run();
    }
  }

  async function payNow() {
    if (!b) return;
    setBusy("pay");
    try {
      const c = await api<{ provider: string; checkout_url: string; amount_paise: number }>(`/payments/${b.id}/checkout`, { method: "POST" });
      router.push({ pathname: "/pay", params: { bookingId: String(b.id), provider: c.provider, url: c.checkout_url, amount: String(c.amount_paise) } });
    } catch (e) {
      Alert.alert("Couldn't start payment", (e as Error).message);
      void reload();
    } finally {
      setBusy(null);
    }
  }

  function notWorking(reason: string) {
    if (!b) return;
    void act("broken", `/bookings/${b.id}/not-working`, { reason }, "We'll cancel this booking and refund you in full right away. The host is told so they can fix it.");
  }

  async function extend(minutes: number) {
    if (!b) return;
    setBusy(`ext${minutes}`);
    try {
      const x = await api<ExtraCheckout>(`/bookings/${b.id}/extend`, { body: { minutes } });
      router.push({
        pathname: "/pay",
        params: { bookingId: String(b.id), extraId: String(x.extra.id), provider: x.provider, url: x.checkout_url, amount: String(x.extra.amount_paise) },
      });
    } catch (e) {
      Alert.alert("Can't extend", (e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function payDue(extraId: number) {
    setBusy(`due${extraId}`);
    try {
      const x = await api<ExtraCheckout>(`/payments/extra/${extraId}/checkout`, { method: "POST" });
      router.push({
        pathname: "/pay",
        params: { bookingId: String(id), extraId: String(extraId), provider: x.provider, url: x.checkout_url, amount: String(x.extra.amount_paise) },
      });
    } catch (e) {
      Alert.alert("Couldn't start payment", (e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function receipt() {
    try {
      const { url } = await api<{ url: string }>(`/bookings/${id}/receipt-link`);
      await Linking.openURL(url);
    } catch (e) {
      Alert.alert("Couldn't open receipt", (e as Error).message);
    }
  }

  function cancelText() {
    if (!b) return "";
    if (!isDriver) return "The driver gets a full refund.";
    if (b.status !== "confirmed") return "You'll get a full refund.";
    return minutesToStart >= 60
      ? "You'll get a full refund."
      : `Your slot starts in under an hour, so you'll get a 50% refund (${rupees(b.amount_paise / 2)}).`;
  }

  function finish() {
    if (!b) return;
    if (b.pricing_mode === "kwh") {
      const value = Number(kwh.replace(",", "."));
      if (!kwh || Number.isNaN(value)) return Alert.alert("Enter units used", "Read the kWh from the charger or meter display.");
      return act("finish", `/bookings/${b.id}/complete`, { kwh_used: value }, `Finish with ${value} kWh?`);
    }
    return act("finish", `/bookings/${b.id}/complete`, {}, "Stop charging and finish this session?");
  }

  const amountLine = b.final_amount_paise != null ? b.final_amount_paise : b.amount_paise;

  return (
    <Screen onRefresh={reload} refreshing={loading}>
      <Card>
        <Row style={{ justifyContent: "space-between" }}>
          <H2>{b.charger.title}</H2>
          <Badge label={st.label} tone={st.tone} />
        </Row>
        <Small>Booking #{b.id}</Small>
        <Divider />
        <InfoRow icon="calendar-outline" text={`${slotLabel(b.start_at, b.end_at)} (${durationLabel(minutes)})`} />
        <InfoRow icon="location-outline" text={b.charger.address} />
        <InfoRow icon="flash-outline" text={`${b.charger.connector_type} · ${b.charger.power_kw} kW`} />
        <InfoRow icon="person-outline" text={`${isDriver ? "Host" : "Driver"}: ${b.other_party_name}`} />
        {!isDriver && (b.vehicle_type || b.vehicle_note) ? <InfoRow icon="car-outline" text={[b.vehicle_type, b.vehicle_note].filter(Boolean).join(" · ")} /> : null}
      </Card>

      {b.access_notes ? <Notice icon="key-outline" tone="green" text={`How to reach the charger: ${b.access_notes}`} /> : null}

      <Card>
        <H2>Payment</H2>
        <Row style={{ justifyContent: "space-between" }}>
          <Body>{b.status === "completed" ? "Final amount" : "Paid upfront"}</Body>
          <Body>{rupees(amountLine, 2)}</Body>
        </Row>
        {b.kwh_used != null && <Small>{b.kwh_used} kWh used</Small>}
        {b.refund_paise > 0 && (
          <Row style={{ justifyContent: "space-between" }}>
            <Body>Refunded</Body>
            <Body>{rupees(b.refund_paise, 2)}</Body>
          </Row>
        )}
        {!isDriver && b.host_earning_paise > 0 && (
          <Row style={{ justifyContent: "space-between" }}>
            <Body style={{ fontWeight: "700" }}>You earn</Body>
            <Body style={{ fontWeight: "700" }}>{rupees(b.host_earning_paise, 2)}</Body>
          </Row>
        )}
        {b.cancel_reason ? <Small>Note: {b.cancel_reason}</Small> : null}
        {b.extras.map((x) => (
          <Row key={x.id} style={{ justifyContent: "space-between" }}>
            <Small>
              {x.kind === "extension" ? `Extended ${x.minutes} min` : `Overstay fee (${x.minutes} min)`} ·{" "}
              {x.status === "due" ? "due" : x.status === "created" ? "not paid" : x.status.replace("_", " ")}
            </Small>
            <Small>{rupees(x.amount_paise, 2)}</Small>
          </Row>
        ))}
        {isDriver &&
          b.extras
            .filter((x) => x.status === "due")
            .map((x) => <Button key={x.id} title={`Pay overstay fee ${rupees(x.amount_paise)}`} onPress={() => payDue(x.id)} loading={busy === `due${x.id}`} />)}
      </Card>
      {!isDriver && b.checklist && b.checklist["at"] ? (
        <Notice tone="green" icon="shield-checkmark-outline" text="Driver confirmed the safety checklist at check-in: cable OK, connector matches, area dry." />
      ) : null}

      <View style={{ gap: space.sm }}>
        {/* ----- driver actions ----- */}
        {isDriver && b.status === "pending_payment" && <Button title="Pay now" icon="card" onPress={payNow} loading={busy === "pay"} />}
        {isDriver && b.status === "requested" && <Notice tone="amber" text="Waiting for the host to accept. If they don't respond before your slot starts, you get a full refund." />}
        {isDriver && b.status === "confirmed" && (
          <>
            <Button title="I've arrived: scan QR" icon="qr-code" onPress={() => router.push(`/scan/${b.id}`)} />
            <Small style={{ textAlign: "center" }}>You can check in from 15 minutes before your slot.</Small>
          </>
        )}
        {(b.status === "confirmed" || b.status === "active") && (
          <Row>
            {isDriver && <Button style={{ flex: 1 }} title="Directions" variant="secondary" icon="navigate" onPress={() => openDirections(b.charger.lat, b.charger.lng, b.charger.title)} />}
            {b.other_party_phone ? (
              <Button style={{ flex: 1 }} title={`Call ${isDriver ? "host" : "driver"}`} variant="secondary" icon="call" onPress={() => callNumber(b.other_party_phone)} />
            ) : null}
          </Row>
        )}
        {isDriver && (b.status === "confirmed" || b.status === "active") && (
          <Card>
            <H2>Need more time?</H2>
            <Small>Extend if the next slot is free. You pay only for the extra time.</Small>
            <Row>
              {[15, 30, 60].map((m) => (
                <Button key={m} style={{ flex: 1 }} title={`+${m} min`} variant="secondary" onPress={() => extend(m)} loading={busy === `ext${m}`} />
              ))}
            </Row>
          </Card>
        )}
        {b.status === "active" && (
          <Card>
            <H2>Charging in progress</H2>
            {b.pricing_mode === "kwh" ? (
              <Field label="Units used (kWh)" placeholder="e.g. 12.4" keyboardType="decimal-pad" value={kwh} onChangeText={setKwh} hint="Read it from the charger or the meter when you unplug." />
            ) : (
              <Small>When you're done, unplug and finish the session.</Small>
            )}
            <Button title="Finish charging" icon="checkmark-circle" onPress={finish} loading={busy === "finish"} />
          </Card>
        )}

        {/* ----- host actions ----- */}
        {!isDriver && b.status === "requested" && (
          <Row>
            <Button style={{ flex: 1 }} title="Accept" icon="checkmark" onPress={() => act("accept", `/bookings/${b.id}/accept`)} loading={busy === "accept"} />
            <Button style={{ flex: 1 }} title="Decline" variant="danger" onPress={() => act("decline", `/bookings/${b.id}/decline`, { reason: "Host declined" }, "The driver will get a full refund.")} loading={busy === "decline"} />
          </Row>
        )}

        {/* ----- both ----- */}
        {["pending_payment", "requested", "confirmed"].includes(b.status) && !(isDriver === false && b.status === "requested") && (
          <Button title="Cancel booking" variant="danger" onPress={() => act("cancel", `/bookings/${b.id}/cancel`, { reason: "" }, cancelText())} loading={busy === "cancel"} />
        )}
        {isDriver && (b.status === "confirmed" || b.status === "active") && (
          <>
            <Button title="Charger not working? Get a full refund" variant="danger" icon="flash-off" onPress={() => setShowBroken(!showBroken)} loading={busy === "broken"} />
            {showBroken && (
              <Card>
                <Small>What's wrong?</Small>
                {["No power / doesn't start", "Connector doesn't fit", "Damaged or unsafe", "Can't get access"].map((r) => (
                  <Button key={r} title={r} variant="secondary" onPress={() => notWorking(r)} />
                ))}
              </Card>
            )}
          </>
        )}
        {["completed", "cancelled", "declined", "expired"].includes(b.status) && b.amount_paise > 0 && (
          <Button title="Download receipt" variant="secondary" icon="receipt-outline" onPress={receipt} />
        )}
        {b.can_review && <Button title={isDriver ? "Rate this charger" : "Rate this driver"} icon="star" onPress={() => router.push(`/review/${b.id}`)} />}
        <Button title="Report a problem" variant="ghost" icon="alert-circle-outline" onPress={() => router.push({ pathname: "/report", params: { bookingId: String(b.id) } })} />
      </View>
    </Screen>
  );
}
