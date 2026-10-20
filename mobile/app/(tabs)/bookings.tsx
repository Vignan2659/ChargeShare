import { router } from "expo-router";
import { useState } from "react";
import { FlatList, View } from "react-native";

import { api } from "../../src/api";
import { BookingRow } from "../../src/BookingRow";
import { colors, space } from "../../src/theme";
import type { Booking } from "../../src/types";
import { Button, Chip, Empty, Row, useLoad } from "../../src/ui";

export default function Bookings() {
  const [scope, setScope] = useState<"upcoming" | "past">("upcoming");
  const { data, loading, reload, error } = useLoad(() => api<Booking[]>(`/bookings?role=driver&scope=${scope}`), [scope]);

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
