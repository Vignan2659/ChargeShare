import { router } from "expo-router";
import { useState } from "react";
import { FlatList, View } from "react-native";

import { api } from "../../src/api";
import { BookingRow } from "../../src/BookingRow";
import { colors, space } from "../../src/theme";
import { rupees } from "../../src/format";
import type { Booking, Extra, WaitlistEntry } from "../../src/types";
import { Button, Card, Chip, Empty, Notice, Row, Small, useLoad } from "../../src/ui";

export default function Bookings() {
  const [scope, setScope] = useState<"upcoming" | "past">("upcoming");
  const { data, loading, reload, error } = useLoad(() => api<Booking[]>(`/bookings?role=driver&scope=${scope}`), [scope]);
  const side = useLoad(async () => {
    const [dues, waitlist] = await Promise.all([api<Extra[]>("/payments/dues"), api<WaitlistEntry[]>("/chargers/waitlist/mine")]);
    return { dues, waitlist };
  });
  const dueTotal = side.data?.dues.reduce((a, x) => a + x.amount_paise, 0) ?? 0;

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <Row style={{ padding: space.lg, paddingBottom: 0 }}>
        <Chip label="Upcoming" selected={scope === "upcoming"} onPress={() => setScope("upcoming")} />
        <Chip label="Past" selected={scope === "past"} onPress={() => setScope("past")} />
      </Row>
      <FlatList
        data={data ?? []}
        keyExtractor={(b) => String(b.id)}
        renderItem={({ item }) => <BookingRow b={item} />}
        contentContainerStyle={{ padding: space.lg, gap: space.md }}
        refreshing={loading}
        onRefresh={reload}
        ListHeaderComponent={
          <View style={{ gap: space.md }}>
            {dueTotal > 0 && (
              <Card onPress={() => router.push("/dues")}>
                <Notice tone="red" icon="alert-circle" text={`You have ${rupees(dueTotal)} in pending overstay fees. Tap to pay. New bookings are paused until then.`} />
              </Card>
            )}
            {scope === "upcoming" && (side.data?.waitlist.length ?? 0) > 0 && (
              <Card>
                <Small>On the waitlist</Small>
                {side.data!.waitlist.map((w) => (
                  <Small key={w.id}>
                    {w.charger_title} · {w.day} {w.notified_at ? "· slot opened! Book now" : "· waiting"}
                  </Small>
                ))}
              </Card>
            )}
          </View>
        }
        ListEmptyComponent={
          loading ? null : (
            <Empty
              icon="calendar-outline"
              title={scope === "upcoming" ? "No upcoming bookings" : "No past bookings"}
              text={error ?? "Find a charger near you and book a slot."}
              action={<Button title="Find a charger" onPress={() => router.navigate("/(tabs)")} />}
            />
          )
        }
      />
    </View>
  );
}
