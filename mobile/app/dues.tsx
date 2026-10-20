import { router } from "expo-router";
import { useState } from "react";
import { Alert } from "react-native";

import { api } from "../src/api";
import { rupees } from "../src/format";
import type { Extra, ExtraCheckout } from "../src/types";
import { Body, Button, Card, Empty, H2, Loading, Notice, Row, Screen, Small, useLoad } from "../src/ui";

export default function Dues() {
  const { data, loading, reload } = useLoad(() => api<Extra[]>("/payments/dues"));
  const [busy, setBusy] = useState<number | null>(null);

  async function pay(x: Extra) {
    setBusy(x.id);
    try {
      const c = await api<ExtraCheckout>(`/payments/extra/${x.id}/checkout`, { method: "POST" });
      router.push({
        pathname: "/pay",
        params: { bookingId: String(x.booking_id), extraId: String(x.id), provider: c.provider, url: c.checkout_url, amount: String(x.amount_paise) },
      });
    } catch (e) {
      Alert.alert("Couldn't start payment", (e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (loading && !data) return <Loading />;
  return (
    <Screen onRefresh={reload} refreshing={loading}>
      <Notice text="Overstay fees apply when a car stays more than 15 minutes after its slot ends, so the next driver isn't kept waiting. Clear dues to book again." />
      {!data?.length ? (
        <Empty icon="checkmark-circle-outline" title="No dues" text="You're all clear." />
      ) : (
        data.map((x) => (
          <Card key={x.id}>
            <Row style={{ justifyContent: "space-between" }}>
              <H2>{rupees(x.amount_paise)}</H2>
              <Small>Booking #{x.booking_id}</Small>
            </Row>
            <Body>Overstay of {x.minutes} minutes</Body>
            <Button title="Pay now" onPress={() => pay(x)} loading={busy === x.id} />
            <Button title="Disagree? Report it" variant="ghost" onPress={() => router.push({ pathname: "/report", params: { bookingId: String(x.booking_id) } })} />
          </Card>
        ))
      )}
    </Screen>
  );
}
