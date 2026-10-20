import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import * as Location from "expo-location";
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Alert, Pressable, View } from "react-native";
import MapView, { Marker } from "react-native-maps";

import { api, uploadImage } from "../../src/api";
import { colors, radius, space } from "../../src/theme";
import type { Community, HostCharger } from "../../src/types";
import { Body, Button, ChipGroup, Field, H2, Loading, Notice, Row, Screen, Small, Toggle } from "../../src/ui";

const CONNECTORS = ["15A socket", "Type 2 (AC)", "CCS2 (DC)", "Bharat AC-001", "Bharat DC-001", "LECCS (2W)", "Ather connector", "Other"];
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

type Form = {
  title: string;
  description: string;
  address: string;
  access_notes: string;
  lat: number | null;
  lng: number | null;
  vehicle_types: string[];
  connector_type: string;
  power_kw: string;
  pricing_mode: "hour" | "kwh";
  price: string; // rupees as typed
  photo_urls: string[];
  allDay: boolean;
  open_time: string;
  close_time: string;
  auto_accept: boolean;
  society_only: boolean;
  society_name: string;
  has_society_noc: boolean;
  area: string;
  offpeak: boolean;
  offpeak_price: string;
  offpeak_start: string;
  offpeak_end: string;
  idle_fee: string; // rupees per 15 min, "0" = none
  community_id: number | null;
};

const EMPTY: Form = {
  title: "",
  description: "",
  address: "",
  access_notes: "",
  lat: null,
  lng: null,
  vehicle_types: ["4W"],
  connector_type: "Type 2 (AC)",
  power_kw: "7.4",
  pricing_mode: "kwh",
  price: "16",
  photo_urls: [],
  allDay: false,
  open_time: "07:00",
  close_time: "22:00",
  auto_accept: false,
  society_only: false,
  society_name: "",
  has_society_noc: false,
  area: "",
  offpeak: false,
  offpeak_price: "12",
  offpeak_start: "22:00",
  offpeak_end: "06:00",
  idle_fee: "0",
  community_id: null,
};

export default function ChargerForm() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const editing = !!id;
  const [f, setF] = useState<Form>(EMPTY);
  const [loaded, setLoaded] = useState(!editing);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [societies, setSocieties] = useState<Community[]>([]);
  const mapRef = useRef<MapView>(null);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((prev) => ({ ...prev, [k]: v }));

  useEffect(() => {
    api<Community[]>("/communities/mine")
      .then((list) => setSocieties(list.filter((c) => c.status === "approved" && (c.role === "manager" || c.my_status === "approved"))))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!editing) {
      void locateMe(false);
      return;
    }
    api<HostCharger>(`/chargers/${id}/manage`)
      .then((c) =>
        setF({
          ...c,
          lat: c.lat,
          lng: c.lng,
          power_kw: String(c.power_kw),
          price: String(c.price_paise / 100),
          allDay: c.open_time === c.close_time,
          offpeak: !!c.offpeak_price_paise,
          offpeak_price: c.offpeak_price_paise ? String(c.offpeak_price_paise / 100) : "12",
          idle_fee: String(c.idle_fee_paise / 100),
        }),
      )
      .catch((e) => Alert.alert("Couldn't load", (e as Error).message))
      .finally(() => setLoaded(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function locateMe(showErrors = true) {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") {
      if (showErrors) Alert.alert("Location is off", "Allow location, or drag the pin to your charger.");
      setF((p) => ({ ...p, lat: p.lat ?? 17.4401, lng: p.lng ?? 78.3489 }));
      return;
    }
    const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
    setF((p) => ({ ...p, lat: pos.coords.latitude, lng: pos.coords.longitude }));
    mapRef.current?.animateToRegion({ latitude: pos.coords.latitude, longitude: pos.coords.longitude, latitudeDelta: 0.005, longitudeDelta: 0.005 });
    if (!f.address) {
      const [place] = await Location.reverseGeocodeAsync(pos.coords).catch(() => []);
      if (place) {
        const parts = [place.name, place.street, place.district, place.city].filter(Boolean);
        setF((p) => ({ ...p, address: p.address || parts.join(", ") }));
      }
    }
  }

  async function addPhoto() {
    if (f.photo_urls.length >= 6) return Alert.alert("Max 6 photos");
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7, allowsEditing: true, aspect: [16, 10] });
    if (res.canceled) return;
    setUploading(true);
    try {
      const up = await uploadImage(res.assets[0].uri, "photo");
      if (up.url) set("photo_urls", [...f.photo_urls, up.url]);
    } catch (e) {
      Alert.alert("Upload failed", (e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function save() {
    const price = Number(f.price.replace(",", "."));
    const power = Number(f.power_kw.replace(",", "."));
    if (f.lat == null || f.lng == null) return Alert.alert("Set the location", "Tap 'Use my location' or drag the pin.");
    if (!(price > 0)) return Alert.alert("Enter a price");
    if (!(power > 0)) return Alert.alert("Enter the charger power in kW");
    if (!f.allDay && (!HHMM.test(f.open_time) || !HHMM.test(f.close_time))) return Alert.alert("Hours must look like 07:30");
    if (f.offpeak && (!HHMM.test(f.offpeak_start) || !HHMM.test(f.offpeak_end) || !(Number(f.offpeak_price) > 0))) return Alert.alert("Check the off-peak price and times (like 22:00)");
    if (f.vehicle_types.length === 0) return Alert.alert("Pick at least one vehicle type");

    const body = {
      title: f.title.trim(),
      description: f.description.trim(),
      address: f.address.trim(),
      access_notes: f.access_notes.trim(),
      lat: f.lat,
      lng: f.lng,
      vehicle_types: f.vehicle_types,
      connector_type: f.connector_type,
      power_kw: power,
      pricing_mode: f.pricing_mode,
      price_paise: Math.round(price * 100),
      photo_urls: f.photo_urls,
      open_time: f.allDay ? "00:00" : f.open_time,
      close_time: f.allDay ? "00:00" : f.close_time,
      auto_accept: f.auto_accept,
      society_only: f.society_only,
      society_name: f.society_name.trim(),
      has_society_noc: f.has_society_noc,
      area: f.area.trim(),
      offpeak_price_paise: f.offpeak ? Math.round(Number(f.offpeak_price.replace(",", ".")) * 100) : editing ? 0 : null,
      offpeak_start: f.offpeak_start,
      offpeak_end: f.offpeak_end,
      idle_fee_paise: Math.round(Number(f.idle_fee.replace(",", ".") || "0") * 100),
      community_id: f.community_id ?? (editing ? 0 : null),
    };
    setBusy(true);
    try {
      if (editing) await api(`/chargers/${id}`, { method: "PATCH", body });
      else await api("/chargers", { body });
      Alert.alert(editing ? "Saved" : "Charger submitted", editing ? "" : "We'll review it shortly. You'll get a notification when it's live.");
      router.back();
    } catch (e) {
      Alert.alert("Couldn't save", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!loaded) return <Loading />;
  const priceHint =
    f.pricing_mode === "kwh"
      ? "Typical home tariff is ₹6–9 per unit. Most hosts charge ₹14–20 per kWh."
      : "Per hour of the booked slot. Scooters typically ₹20–40/hr, cars ₹80–150/hr.";

  return (
    <Screen>
      <H2>Photos</H2>
      <Row style={{ flexWrap: "wrap" }}>
        {f.photo_urls.map((u) => (
          <Pressable key={u} onLongPress={() => set("photo_urls", f.photo_urls.filter((x) => x !== u))}>
            <Image source={{ uri: u }} style={{ width: 96, height: 64, borderRadius: 8 }} />
          </Pressable>
        ))}
        <Pressable onPress={addPhoto} style={{ width: 96, height: 64, borderRadius: 8, borderWidth: 1, borderStyle: "dashed", borderColor: colors.muted, alignItems: "center", justifyContent: "center" }}>
          <Ionicons name={uploading ? "hourglass" : "add"} size={26} color={colors.muted} />
        </Pressable>
      </Row>
      <Small>Add the charger, the parking spot and the entrance. Long-press a photo to remove it.</Small>

      <Field label="Listing title" value={f.title} onChangeText={(v) => set("title", v)} placeholder="e.g. Villa charger near Gachibowli flyover" maxLength={120} />
      <Field label="Description" value={f.description} onChangeText={(v) => set("description", v)} multiline placeholder="Covered parking, CCTV, wait in the lobby…" />

      <H2>Location</H2>
      <View style={{ height: 220, borderRadius: radius.md, overflow: "hidden", borderWidth: 1, borderColor: colors.border }}>
        {f.lat != null && f.lng != null ? (
          <MapView
            ref={mapRef}
            style={{ flex: 1 }}
            initialRegion={{ latitude: f.lat, longitude: f.lng, latitudeDelta: 0.005, longitudeDelta: 0.005 }}
            onPress={(e) => setF((p) => ({ ...p, lat: e.nativeEvent.coordinate.latitude, lng: e.nativeEvent.coordinate.longitude }))}
          >
            <Marker
              draggable
              coordinate={{ latitude: f.lat, longitude: f.lng }}
              onDragEnd={(e) => setF((p) => ({ ...p, lat: e.nativeEvent.coordinate.latitude, lng: e.nativeEvent.coordinate.longitude }))}
            />
          </MapView>
        ) : (
          <Loading />
        )}
      </View>
      <Button title="Use my location" variant="secondary" icon="locate" onPress={() => locateMe(true)} />
      <Small>Tap the map or drag the pin to the exact parking spot.</Small>
      <Field label="Address" value={f.address} onChangeText={(v) => set("address", v)} placeholder="Flat/house, street, area, city" />
      <Field
        label="Area shown on the map"
        value={f.area}
        onChangeText={(v) => set("area", v)}
        placeholder="e.g. Kondapur"
        hint="Drivers see only this area and an approximate pin until you confirm their booking."
      />
      <Field
        label="Access instructions (only shown after booking is confirmed)"
        value={f.access_notes}
        onChangeText={(v) => set("access_notes", v)}
        multiline
        placeholder="Gate number, parking slot, who to call at the gate…"
      />

      <H2>Charger</H2>
      <Body>Vehicles it can charge</Body>
      <ChipGroup
        multi
        options={[
          { label: "Scooter / bike", value: "2W" },
          { label: "Auto", value: "3W" },
          { label: "Car", value: "4W" },
        ]}
        value={f.vehicle_types}
        onChange={(v) => set("vehicle_types", v as string[])}
      />
      <Body>Connector</Body>
      <ChipGroup options={CONNECTORS.map((c) => ({ label: c, value: c }))} value={f.connector_type} onChange={(v) => set("connector_type", v as string)} />
      <Field label="Power (kW)" value={f.power_kw} onChangeText={(v) => set("power_kw", v)} keyboardType="decimal-pad" hint="Written on the charger. A normal 15A plug is about 3.3 kW." />

      <H2>Price</H2>
      <ChipGroup
        options={[
          { label: "Per unit (kWh)", value: "kwh" },
          { label: "Per hour", value: "hour" },
        ]}
        value={f.pricing_mode}
        onChange={(v) => set("pricing_mode", v as "hour" | "kwh")}
      />
      <Field label={`Price in ₹ per ${f.pricing_mode === "kwh" ? "kWh" : "hour"}`} value={f.price} onChangeText={(v) => set("price", v)} keyboardType="decimal-pad" hint={priceHint} />
      <Small>ChargeShare keeps a 10% service fee from each booking.</Small>

      <H2>Hours</H2>
      <Toggle label="Available 24 hours" value={f.allDay} onChange={(v) => set("allDay", v)} />
      {!f.allDay && (
        <Row>
          <View style={{ flex: 1 }}>
            <Field label="Opens (24h)" value={f.open_time} onChangeText={(v) => set("open_time", v)} placeholder="07:00" maxLength={5} />
          </View>
          <View style={{ flex: 1 }}>
            <Field label="Closes (24h)" value={f.close_time} onChangeText={(v) => set("close_time", v)} placeholder="22:00" maxLength={5} />
          </View>
        </Row>
      )}

      <H2>Off-peak price (optional)</H2>
      <Toggle
        label="Cheaper rate at night or solar hours"
        hint="Pass on your lower time-of-day electricity rate. Drivers see it when they book."
        value={f.offpeak}
        onChange={(v) => set("offpeak", v)}
      />
      {f.offpeak && (
        <>
          <Field label={`Off-peak price in ₹ per ${f.pricing_mode === "kwh" ? "kWh" : "hour"}`} value={f.offpeak_price} onChangeText={(v) => set("offpeak_price", v)} keyboardType="decimal-pad" />
          <Row>
            <View style={{ flex: 1 }}>
              <Field label="From (24h)" value={f.offpeak_start} onChangeText={(v) => set("offpeak_start", v)} maxLength={5} />
            </View>
            <View style={{ flex: 1 }}>
              <Field label="To (24h)" value={f.offpeak_end} onChangeText={(v) => set("offpeak_end", v)} maxLength={5} />
            </View>
          </Row>
        </>
      )}

      <H2>Overstay fee (optional)</H2>
      <Field
        label="₹ per 15 minutes after the slot ends"
        value={f.idle_fee}
        onChangeText={(v) => set("idle_fee", v)}
        keyboardType="decimal-pad"
        hint="Charged only if a car stays more than 15 minutes past its slot. 0 = no fee."
      />

      {societies.length > 0 && (
        <>
          <H2>Housing society</H2>
          <ChipGroup
            options={[{ label: "Open to everyone", value: "0" }, ...societies.map((c) => ({ label: `Residents of ${c.name}`, value: String(c.id) }))]}
            value={String(f.community_id ?? 0)}
            onChange={(v) => set("community_id", v === "0" ? null : Number(v))}
          />
          <Small>Society chargers are hidden from everyone except approved residents.</Small>
        </>
      )}

      <H2>Booking rules</H2>
      <Toggle label="Instant booking" hint="Bookings are confirmed without your approval." value={f.auto_accept && !f.society_only} onChange={(v) => set("auto_accept", v)} />
      <Toggle
        label="Only residents of my society"
        hint="Safer for gated communities: you approve each driver before they come in."
        value={f.society_only}
        onChange={(v) => set("society_only", v)}
      />
      {f.society_only && <Field label="Society / apartment name" value={f.society_name} onChangeText={(v) => set("society_name", v)} />}
      <Toggle label="My housing society has approved sharing this charger" value={f.has_society_noc} onChange={(v) => set("has_society_noc", v)} />
      {!f.has_society_noc && <Notice tone="amber" text="If your charger is in a shared parking area, get written permission (NOC) from your society or RWA before letting outsiders in." />}

      <View style={{ height: space.sm }} />
      <Button title={editing ? "Save changes" : "Submit for review"} onPress={save} loading={busy} disabled={f.title.trim().length < 3 || f.address.trim().length < 5} />
      {editing && <Small style={{ textAlign: "center" }}>Changing location, photos, title or charger details sends the listing for a quick re-review.</Small>}
    </Screen>
  );
}
