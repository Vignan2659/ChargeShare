import { Ionicons } from "@expo/vector-icons";
import * as Location from "expo-location";
import { router } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";
import MapView, { Marker, type Region } from "react-native-maps";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "../../src/api";
import { useAuth } from "../../src/auth";
import { hoursLabel, priceLabel } from "../../src/format";
import { colors, radius, space } from "../../src/theme";
import type { Charger } from "../../src/types";
import { Badge, Body, Card, Chip, Empty, Row, Small, Stars } from "../../src/ui";

const FALLBACK = { latitude: 17.4401, longitude: 78.3489 }; // Hyderabad, used if location is off
type Vehicle = "" | "2W" | "3W" | "4W";

export default function Find() {
  const { user } = useAuth();
  const mapRef = useRef<MapView>(null);
  const [center, setCenter] = useState(FALLBACK);
  const [region, setRegion] = useState<Region | null>(null);
  const [moved, setMoved] = useState(false);
  const [chargers, setChargers] = useState<Charger[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"map" | "list">("map");
  const [vehicle, setVehicle] = useState<Vehicle>((user?.vehicle_type as Vehicle) ?? "");
  const [selected, setSelected] = useState<Charger | null>(null);

  const search = useCallback(
    async (lat: number, lng: number, radiusKm = 10) => {
      setLoading(true);
      try {
        const qs = new URLSearchParams({ lat: String(lat), lng: String(lng), radius_km: String(Math.min(50, Math.max(2, radiusKm))) });
        if (vehicle) qs.set("vehicle", vehicle);
        setChargers(await api<Charger[]>(`/chargers?${qs}`));
        setError(null);
        setMoved(false);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [vehicle],
  );

  useEffect(() => {
    (async () => {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status === "granted") {
        const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }).catch(() => null);
        if (pos) {
          const c = { latitude: pos.coords.latitude, longitude: pos.coords.longitude };
          setCenter(c);
          mapRef.current?.animateToRegion({ ...c, latitudeDelta: 0.08, longitudeDelta: 0.08 }, 500);
          return search(c.latitude, c.longitude);
        }
      }
      return search(FALLBACK.latitude, FALLBACK.longitude);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // re-run when the vehicle filter changes (skip the very first render; the location effect searches then)
  const firstRun = useRef(true);
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      return;
    }
    const r = region ?? { ...center, latitudeDelta: 0.08 };
    void search(r.latitude, r.longitude, (r.latitudeDelta * 111) / 2);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vehicle]);

  const searchHere = () => {
    if (!region) return;
    void search(region.latitude, region.longitude, (region.latitudeDelta * 111) / 2);
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={["top"]}>
      <View style={styles.topBar}>
        <Row style={{ justifyContent: "space-between" }}>
          <Text style={styles.title}>Chargers near you</Text>
          <Pressable onPress={() => setMode(mode === "map" ? "list" : "map")} style={styles.toggle}>
            <Ionicons name={mode === "map" ? "list" : "map"} size={18} color={colors.primaryDark} />
            <Text style={{ color: colors.primaryDark, fontWeight: "600" }}>{mode === "map" ? "List" : "Map"}</Text>
          </Pressable>
        </Row>
        <Row style={{ flexWrap: "wrap" }}>
          {(["", "2W", "3W", "4W"] as Vehicle[]).map((v) => (
            <Chip key={v || "all"} label={v === "" ? "All" : v === "2W" ? "Scooter" : v === "3W" ? "Auto" : "Car"} selected={vehicle === v} onPress={() => setVehicle(v)} />
          ))}
        </Row>
      </View>

      {mode === "map" ? (
        <View style={{ flex: 1 }}>
          <MapView
            ref={mapRef}
            style={StyleSheet.absoluteFill}
            initialRegion={{ ...center, latitudeDelta: 0.08, longitudeDelta: 0.08 }}
            showsUserLocation
            showsMyLocationButton
            onRegionChangeComplete={(r) => {
              setRegion(r);
              setMoved(true);
            }}
            onPress={() => setSelected(null)}
          >
            {chargers.map((c) => (
              <Marker key={c.id} coordinate={{ latitude: c.lat, longitude: c.lng }} onPress={() => setSelected(c)}>
                <View style={[styles.pin, selected?.id === c.id && { backgroundColor: colors.primaryDark }]}>
                  <Ionicons name="flash" size={12} color="#fff" />
                  <Text style={styles.pinText}>{priceLabel(c)}</Text>
                </View>
              </Marker>
            ))}
          </MapView>
          {moved && (
            <Pressable style={styles.searchHere} onPress={searchHere}>
              <Text style={{ color: colors.primaryDark, fontWeight: "700" }}>{loading ? "Searching…" : "Search this area"}</Text>
            </Pressable>
          )}
          {selected && (
            <View style={styles.sheet}>
              <ChargerCard c={selected} />
            </View>
          )}
          {!loading && chargers.length === 0 && !selected && (
            <View style={styles.sheet}>
              <Card>
                <Body>{error ?? "No chargers here yet. Move the map or try another vehicle filter."}</Body>
              </Card>
            </View>
          )}
        </View>
      ) : (
        <FlatList
          data={chargers}
          keyExtractor={(c) => String(c.id)}
          contentContainerStyle={{ padding: space.lg, gap: space.md }}
          refreshing={loading}
          onRefresh={() => (region ? searchHere() : search(center.latitude, center.longitude))}
          renderItem={({ item }) => <ChargerCard c={item} />}
          ListEmptyComponent={<Empty icon="flash-off-outline" title="No chargers nearby" text={error ?? "Be the first host in your area!"} />}
        />
      )}
    </SafeAreaView>
  );
}

function ChargerCard({ c }: { c: Charger }) {
  return (
    <Card onPress={() => router.push(`/charger/${c.id}`)}>
      <Row style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={{ fontSize: 16, fontWeight: "700", color: colors.text }}>{c.title}</Text>
          <Small>
            {c.distance_km != null ? `${c.distance_km.toFixed(1)} km · ` : ""}
            {c.connector_type} · {c.power_kw} kW
          </Small>
        </View>
        <Text style={{ fontSize: 16, fontWeight: "700", color: colors.primaryDark }}>{priceLabel(c)}</Text>
      </Row>
      <Row style={{ flexWrap: "wrap" }}>
        <Stars value={c.rating_avg} />
        <Small>· {hoursLabel(c.open_time, c.close_time)}</Small>
        {c.safety_checked && <Badge label="Safety checked" tone="green" />}
        {c.auto_accept && <Badge label="Instant book" tone="blue" />}
        {c.society_only && <Badge label={`Residents only${c.society_name ? `: ${c.society_name}` : ""}`} tone="amber" />}
      </Row>
    </Card>
  );
}

const styles = StyleSheet.create({
  topBar: { paddingHorizontal: space.lg, paddingBottom: space.md, paddingTop: space.sm, gap: space.sm, backgroundColor: colors.bg },
  title: { fontSize: 22, fontWeight: "700", color: colors.text },
  toggle: { flexDirection: "row", gap: 6, alignItems: "center", backgroundColor: colors.primarySoft, paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill },
  pin: { flexDirection: "row", alignItems: "center", gap: 2, backgroundColor: colors.primary, paddingHorizontal: 8, paddingVertical: 4, borderRadius: radius.pill, borderWidth: 2, borderColor: "#fff" },
  pinText: { color: "#fff", fontWeight: "700", fontSize: 12 },
  searchHere: { position: "absolute", top: space.md, alignSelf: "center", backgroundColor: "#fff", paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.pill, elevation: 3, shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 6, shadowOffset: { width: 0, height: 2 } },
  sheet: { position: "absolute", left: space.lg, right: space.lg, bottom: space.lg },
});
