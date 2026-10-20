import { Image } from "expo-image";
import { router, useLocalSearchParams } from "expo-router";
import { ScrollView, useWindowDimensions, View } from "react-native";

import { api } from "../../src/api";
import { useAuth } from "../../src/auth";
import { openDirections } from "../../src/links";
import { hoursLabel, parseUtc, priceLabel, slotLabel } from "../../src/format";
import { space } from "../../src/theme";
import type { ChargerDetail } from "../../src/types";
import { Badge, Body, Button, Card, Divider, Empty, H1, H2, InfoRow, Loading, Notice, Row, Screen, Small, Stars, useLoad } from "../../src/ui";

export default function ChargerScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const { width } = useWindowDimensions();
  const { data: c, error, loading } = useLoad(() => api<ChargerDetail>(`/chargers/${id}`), [id]);

  if (loading && !c) return <Loading />;
  if (!c) return <Empty title="Couldn't load charger" text={error ?? ""} />;
  const mine = c.host_id === user?.id;
  const upcoming = c.busy.filter((b) => parseUtc(b.end_at) > new Date()).slice(0, 6);

  return (
    <Screen padded={false}>
      {c.photo_urls.length > 0 && (
        <ScrollView horizontal pagingEnabled showsHorizontalScrollIndicator={false}>
          {c.photo_urls.map((u) => (
            <Image key={u} source={{ uri: u }} style={{ width, height: 220 }} contentFit="cover" />
          ))}
        </ScrollView>
      )}
      <View style={{ padding: space.lg, gap: space.md }}>
        <H1>{c.title}</H1>
        <Row style={{ flexWrap: "wrap" }}>
          <Stars value={c.rating_avg} />
          {c.rating_count > 0 && <Small>({c.rating_count} reviews)</Small>}
          {c.safety_checked && <Badge label="Safety checked" tone="green" />}
          {c.auto_accept && <Badge label="Instant book" tone="blue" />}
        </Row>
        <Card>
          <Row style={{ justifyContent: "space-between" }}>
            <H2>{priceLabel(c)}</H2>
            <Small>Hosted by {c.host_name}</Small>
          </Row>
          <Divider />
          <InfoRow icon="flash-outline" text={`${c.connector_type} · ${c.power_kw} kW`} />
          <InfoRow icon="car-outline" text={`Suitable for: ${c.vehicle_types.map((v) => (v === "2W" ? "scooters/bikes" : v === "3W" ? "autos" : "cars")).join(", ")}`} />
          <InfoRow icon="time-outline" text={hoursLabel(c.open_time, c.close_time)} />
          <InfoRow icon="location-outline" text={c.address} />
          {c.distance_km != null && <InfoRow icon="navigate-outline" text={`${c.distance_km.toFixed(1)} km away`} />}
        </Card>

        {c.pricing_mode === "kwh" && (
          <Notice text="Priced per unit (kWh). You pay the maximum for your slot upfront; unused units are refunded automatically after charging." />
        )}
        {c.society_only && (
          <Notice tone="amber" icon="business-outline" text={`Only for residents${c.society_name ? ` of ${c.society_name}` : ""}. The host will confirm before accepting.`} />
        )}
        {c.description ? <Body>{c.description}</Body> : null}

        {upcoming.length > 0 && (
          <Card>
            <H2>Already booked</H2>
            {upcoming.map((b) => (
              <Small key={b.start_at}>{slotLabel(b.start_at, b.end_at)}</Small>
            ))}
          </Card>
        )}

        <Button title="Directions" variant="secondary" icon="navigate" onPress={() => openDirections(c.lat, c.lng, c.title)} />
        {mine ? (
          <Notice text="This is your own charger." />
        ) : (
          <Button title="Book a slot" icon="calendar" onPress={() => router.push(`/book/${c.id}`)} />
        )}

        <H2>Reviews</H2>
        {c.reviews.length === 0 ? (
          <Small>No reviews yet.</Small>
        ) : (
          c.reviews.map((r) => (
            <Card key={r.id}>
              <Row style={{ justifyContent: "space-between" }}>
                <Body style={{ fontWeight: "600" }}>{r.author_name}</Body>
                <Stars value={r.rating} />
              </Row>
              {r.comment ? <Body>{r.comment}</Body> : null}
            </Card>
          ))
        )}
        <Button title="Report this listing" variant="ghost" onPress={() => router.push({ pathname: "/report", params: { chargerId: String(c.id) } })} />
      </View>
    </Screen>
  );
}
