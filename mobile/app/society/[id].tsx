import * as Clipboard from "expo-clipboard";
import { useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Alert, Text, View } from "react-native";

import { api } from "../../src/api";
import { rupees } from "../../src/format";
import { colors, space } from "../../src/theme";
import type { Community, Member, Statement } from "../../src/types";
import { Badge, Body, Button, Card, Chip, Divider, H2, Loading, Row, Screen, Small, useLoad } from "../../src/ui";

const monthKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
const MONTHS = Array.from({ length: 4 }, (_, i) => {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - i);
  return d;
});

export default function SocietyManage() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [month, setMonth] = useState(monthKey(new Date()));
  const { data, loading, reload } = useLoad(async () => {
    const [list, members, statement] = await Promise.all([
      api<Community[]>("/communities/mine"),
      api<Member[]>(`/communities/${id}/members`),
      api<Statement>(`/communities/${id}/statement?month=${month}`),
    ]);
    return { community: list.find((c) => String(c.id) === id) ?? null, members, statement };
  }, [id, month]);

  async function decide(m: Member, action: "approve" | "reject" | "remove") {
    try {
      await api(`/communities/${id}/members/${m.id}/${action}`, { method: "POST" });
      void reload();
    } catch (e) {
      Alert.alert("Couldn't update", (e as Error).message);
    }
  }

  if (loading && !data) return <Loading />;
  if (!data?.community) return null;
  const c = data.community;
  const pending = data.members.filter((m) => m.status === "pending");
  const approved = data.members.filter((m) => m.status === "approved");

  return (
    <Screen onRefresh={reload} refreshing={loading}>
      <Card>
        <H2>{c.name}</H2>
        <Small>{c.address}</Small>
        {c.status === "approved" ? (
          <Row style={{ justifyContent: "space-between" }}>
            <Body>
              Join code: <Text style={{ fontWeight: "800", letterSpacing: 2 }}>{c.code}</Text>
            </Body>
            <Button
              title="Copy"
              variant="secondary"
              style={{ paddingVertical: 6, minHeight: 34 }}
              onPress={async () => {
                await Clipboard.setStringAsync(c.code);
                Alert.alert("Copied", "Share it in your society WhatsApp group.");
              }}
            />
          </Row>
        ) : (
          <Badge label={`Verification ${c.status}`} tone="amber" />
        )}
      </Card>

      <H2>Requests to join ({pending.length})</H2>
      {pending.length === 0 && <Small>No pending requests.</Small>}
      {pending.map((m) => (
        <Card key={m.id}>
          <Body style={{ fontWeight: "700" }}>
            {m.name || "Resident"} · Flat {m.flat}
          </Body>
          <Small>{m.phone}</Small>
          <Row>
            <Button style={{ flex: 1 }} title="Approve" onPress={() => decide(m, "approve")} />
            <Button style={{ flex: 1 }} title="Reject" variant="danger" onPress={() => decide(m, "reject")} />
          </Row>
        </Card>
      ))}

      <H2>Residents ({approved.length})</H2>
      <Card>
        {approved.map((m, i) => (
          <View key={m.id} style={{ gap: 2 }}>
            {i > 0 && <Divider />}
            <Row style={{ justifyContent: "space-between" }}>
              <Body>
                {m.flat} · {m.name}
              </Body>
              {m.user_id !== c.manager_id && (
                <Text style={{ color: colors.danger, fontWeight: "600" }} onPress={() => decide(m, "remove")}>
                  Remove
                </Text>
              )}
            </Row>
          </View>
        ))}
      </Card>

      <H2>Monthly usage statement</H2>
      <Row style={{ flexWrap: "wrap" }}>
        {MONTHS.map((d) => (
          <Chip key={monthKey(d)} label={d.toLocaleDateString("en-IN", { month: "short", year: "numeric" })} selected={month === monthKey(d)} onPress={() => setMonth(monthKey(d))} />
        ))}
      </Row>
      <Card>
        <Row style={{ justifyContent: "space-between" }}>
          <Small style={{ flex: 2 }}>Flat</Small>
          <Small style={{ flex: 1, textAlign: "right" }}>Sessions</Small>
          <Small style={{ flex: 1, textAlign: "right" }}>kWh</Small>
          <Small style={{ flex: 1.3, textAlign: "right" }}>Paid</Small>
        </Row>
        <Divider />
        {data.statement.rows.length === 0 && <Small>No charging sessions this month.</Small>}
        {data.statement.rows.map((r) => (
          <Row key={r.flat} style={{ justifyContent: "space-between", paddingVertical: space.xs }}>
            <Body style={{ flex: 2 }}>{r.flat}</Body>
            <Body style={{ flex: 1, textAlign: "right" }}>{r.sessions}</Body>
            <Body style={{ flex: 1, textAlign: "right" }}>{r.kwh}</Body>
            <Body style={{ flex: 1.3, textAlign: "right" }}>{rupees(r.amount_paise)}</Body>
          </Row>
        ))}
        <Divider />
        <Row style={{ justifyContent: "space-between" }}>
          <Body style={{ fontWeight: "700" }}>Total</Body>
          <Body style={{ fontWeight: "700" }}>
            {data.statement.total_kwh} kWh · {rupees(data.statement.total_amount_paise)}
          </Body>
        </Row>
        <Small>For hourly sessions, energy is estimated from charger power × time. Use this to settle common-meter electricity fairly.</Small>
      </Card>
    </Screen>
  );
}
