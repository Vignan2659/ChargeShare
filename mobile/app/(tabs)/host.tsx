import { Image } from "expo-image";
import { router } from "expo-router";
import { Text, View } from "react-native";

import { api } from "../../src/api";
import { useAuth } from "../../src/auth";
import { priceLabel, rupees } from "../../src/format";
import { colors, space } from "../../src/theme";
import type { Booking, Earnings, HostCharger } from "../../src/types";
import { Badge, Body, Button, Card, Empty, H2, Notice, Row, Screen, Small, useLoad } from "../../src/ui";
import { BookingRow } from "../../src/BookingRow";

const CHARGER_STATUS: Record<HostCharger["status"], { label: string; tone: "green" | "amber" | "red" | "grey" }> = {
  pending: { label: "In review", tone: "amber" },
  approved: { label: "Live", tone: "green" },
  rejected: { label: "Needs changes", tone: "red" },
  paused: { label: "Paused", tone: "grey" },
  removed: { label: "Removed", tone: "grey" },
};

export default function Host() {
  const { user, refresh } = useAuth();
  const status = user?.host_status ?? "none";
  const canList = status === "pending" || status === "approved";

  const { data, loading, reload } = useLoad(async () => {
    await refresh();
    if (!canList) return null;
    const [chargers, upcoming, earnings] = await Promise.all([
      api<HostCharger[]>("/chargers/mine"),
      api<Booking[]>("/bookings?role=host&scope=upcoming"),
      api<Earnings>("/me/earnings"),
    ]);
    return { chargers, upcoming, earnings };
  }, [canList]);

  if (status === "none" || status === "rejected") {
    return (
      <Screen>
        <Empty
          icon="home-outline"
          title="Earn from your charger"
          text="List your home or society charger. Set your own price and hours. Get paid weekly to your UPI."
        />
        {status === "rejected" && <Notice tone="red" text={`Your last application wasn't approved: ${user?.host_note || "please re-upload a clear ID."}`} />}
        <Card>
          <Body>How it works</Body>
          <Small>1. Verify your ID and add your UPI ID</Small>
          <Small>2. Add your charger with photos, price and hours</Small>
          <Small>3. We review it (usually within a day)</Small>
          <Small>4. Accept bookings, drivers scan your QR code, you earn</Small>
        </Card>
        <Button title={status === "rejected" ? "Apply again" : "Become a host"} onPress={() => router.push("/host/apply")} />
      </Screen>
    );
  }

  const pending = data?.upcoming.filter((b) => b.status === "requested") ?? [];
  const others = data?.upcoming.filter((b) => b.status !== "requested") ?? [];

  return (
    <Screen onRefresh={reload} refreshing={loading}>
      {status === "pending" && <Notice tone="amber" text="Your host verification is in review. You can add chargers now; they go live once approved." />}

      {data && (
        <Card onPress={() => router.push("/host/earnings")}>
          <Row style={{ justifyContent: "space-between" }}>
            <View>
              <Small>This month</Small>
              <Text style={{ fontSize: 26, fontWeight: "800", color: colors.text }}>{rupees(data.earnings.this_month_paise)}</Text>
            </View>
            <View style={{ alignItems: "flex-end" }}>
              <Small>Next payout</Small>
              <Text style={{ fontSize: 18, fontWeight: "700", color: colors.primaryDark }}>{rupees(data.earnings.pending_payout_paise)}</Text>
            </View>
          </Row>
          <Small>{data.earnings.completed_sessions} sessions completed · See earnings ›</Small>
        </Card>
      )}

      {pending.length > 0 && (
        <>
          <H2>Requests waiting for you ({pending.length})</H2>
          {pending.map((b) => (
            <BookingRow key={b.id} b={b} showEarning />
          ))}
        </>
      )}

      <H2>Upcoming</H2>
      {others.length === 0 ? <Small>No upcoming bookings.</Small> : others.map((b) => <BookingRow key={b.id} b={b} showEarning />)}

      <Row style={{ justifyContent: "space-between", marginTop: space.sm }}>
        <H2>My chargers</H2>
        <Button title="Add" icon="add" variant="secondary" onPress={() => router.push("/host/charger-form")} style={{ paddingVertical: 8, minHeight: 36 }} />
      </Row>
      {data?.chargers.length === 0 && <Small>You haven't added a charger yet.</Small>}
      {data?.chargers.map((c) => (
        <Card key={c.id} onPress={() => router.push(`/host/charger/${c.id}`)}>
          <Row style={{ alignItems: "flex-start" }}>
            {c.photo_urls[0] ? (
              <Image source={{ uri: c.photo_urls[0] }} style={{ width: 64, height: 64, borderRadius: 10 }} />
            ) : null}
            <View style={{ flex: 1, gap: 4 }}>
              <Row style={{ justifyContent: "space-between" }}>
                <Text style={{ flex: 1, fontSize: 16, fontWeight: "700", color: colors.text }}>{c.title}</Text>
                <Badge label={CHARGER_STATUS[c.status].label} tone={CHARGER_STATUS[c.status].tone} />
              </Row>
              <Small>
                {priceLabel(c)} · {c.power_kw} kW · {c.connector_type}
              </Small>
              {c.status === "rejected" && c.admin_note ? <Small style={{ color: colors.danger }}>{c.admin_note}</Small> : null}
            </View>
          </Row>
        </Card>
      ))}
    </Screen>
  );
}
