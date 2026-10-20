import { router } from "expo-router";
import { Text } from "react-native";

import { rupees, slotLabel, STATUS_TEXT } from "./format";
import { colors } from "./theme";
import type { Booking } from "./types";
import { Badge, Card, Row, Small } from "./ui";

export function BookingRow({ b, showEarning = false }: { b: Booking; showEarning?: boolean }) {
  const st = STATUS_TEXT[b.status];
  return (
    <Card onPress={() => router.push(`/booking/${b.id}`)}>
      <Row style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <Text style={{ flex: 1, fontSize: 16, fontWeight: "700", color: colors.text }}>{b.charger.title}</Text>
        <Badge label={st.label} tone={st.tone} />
      </Row>
      <Small>{slotLabel(b.start_at, b.end_at)}</Small>
      <Row style={{ justifyContent: "space-between" }}>
        <Small>{showEarning ? `Driver: ${b.other_party_name}` : b.charger.address}</Small>
        <Text style={{ fontWeight: "700", color: colors.text }}>
          {showEarning && b.host_earning_paise ? `+${rupees(b.host_earning_paise)}` : rupees(b.final_amount_paise ?? b.amount_paise)}
        </Text>
      </Row>
    </Card>
  );
}
