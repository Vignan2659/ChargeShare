import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Alert, View } from "react-native";
import QRCode from "react-native-qrcode-svg";

import { api } from "../../../src/api";
import { hoursLabel, priceLabel } from "../../../src/format";
import { space } from "../../../src/theme";
import type { HostCharger } from "../../../src/types";
import { Badge, Body, Button, Card, Empty, H2, Loading, Notice, Row, Screen, Small, Stars, useLoad } from "../../../src/ui";

export default function ManageCharger() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data: c, loading, reload, setData, error } = useLoad(() => api<HostCharger>(`/chargers/${id}/manage`), [id]);
  const [busy, setBusy] = useState<string | null>(null);

  if (loading && !c) return <Loading />;
  if (!c) return <Empty title="Couldn't load charger" text={error ?? ""} />;

  async function patch(key: string, body: object) {
    setBusy(key);
    try {
      setData(await api<HostCharger>(`/chargers/${id}`, { method: "PATCH", body }));
    } catch (e) {
      Alert.alert("Couldn't update", (e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function regenerate() {
    Alert.alert("New QR code?", "The old QR sticker will stop working. Print and stick the new one.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Generate",
        onPress: async () => {
          try {
            setData(await api<HostCharger>(`/chargers/${id}/regenerate-qr`, { method: "POST" }));
          } catch (e) {
            Alert.alert("Couldn't regenerate", (e as Error).message);
          }
        },
      },
    ]);
  }

  function remove() {
    Alert.alert("Remove this charger?", "It will disappear from the map. You can't undo this.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Remove",
        style: "destructive",
        onPress: async () => {
          try {
            await api(`/chargers/${id}`, { method: "DELETE" });
            router.back();
          } catch (e) {
            Alert.alert("Couldn't remove", (e as Error).message);
          }
        },
      },
    ]);
  }

  const statusTone = c.status === "approved" ? "green" : c.status === "rejected" ? "red" : c.status === "paused" ? "grey" : "amber";
  const statusText = { pending: "In review", approved: "Live", rejected: "Needs changes", paused: "Paused", removed: "Removed" }[c.status];

  return (
    <Screen onRefresh={reload} refreshing={loading}>
      <Card>
        <Row style={{ justifyContent: "space-between" }}>
          <H2>{c.title}</H2>
          <Badge label={statusText} tone={statusTone} />
        </Row>
        <Small>
          {priceLabel(c)} · {c.power_kw} kW · {hoursLabel(c.open_time, c.close_time)}
        </Small>
        <Stars value={c.rating_avg} />
      </Card>
      {c.admin_note ? <Notice tone={c.status === "rejected" ? "red" : "blue"} text={`From our team: ${c.admin_note}`} /> : null}

      <Card style={{ alignItems: "center" }}>
        <H2>Charger QR code</H2>
        <Small style={{ textAlign: "center" }}>
          Print this and stick it next to the charger. Drivers scan it to start their session. Take a screenshot to print.
        </Small>
        <View style={{ padding: space.md, backgroundColor: "#fff" }}>
          <QRCode value={`chargeshare:qr:${c.qr_token}`} size={200} />
        </View>
        <Body style={{ fontFamily: "monospace", letterSpacing: 1 }}>{c.qr_token}</Body>
        <Small>Code for manual entry</Small>
        <Button title="Generate new QR" variant="ghost" onPress={regenerate} />
      </Card>

      {c.status === "approved" && <Button title="Pause bookings" icon="pause" variant="secondary" onPress={() => patch("pause", { paused: true })} loading={busy === "pause"} />}
      {c.status === "paused" && <Button title="Resume bookings" icon="play" onPress={() => patch("pause", { paused: false })} loading={busy === "pause"} />}
      <Button title="Edit details" icon="create" variant="secondary" onPress={() => router.push({ pathname: "/host/charger-form", params: { id: String(c.id) } })} />
      <Button title="See public listing" variant="ghost" onPress={() => router.push(`/charger/${c.id}`)} />
      <Button title="Remove charger" variant="danger" onPress={remove} />
    </Screen>
  );
}
