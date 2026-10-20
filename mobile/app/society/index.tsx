import { router } from "expo-router";
import { useState } from "react";
import { Alert, Text } from "react-native";

import { api } from "../../src/api";
import { colors } from "../../src/theme";
import type { Community } from "../../src/types";
import { Badge, Body, Button, Card, Field, H2, Loading, Notice, Row, Screen, Small, useLoad } from "../../src/ui";

export default function Societies() {
  const { data, loading, reload } = useLoad(() => api<Community[]>("/communities/mine"));
  const [code, setCode] = useState("");
  const [flat, setFlat] = useState("");
  const [mode, setMode] = useState<"none" | "join" | "create">("none");
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);

  async function join() {
    setBusy(true);
    try {
      await api("/communities/join", { body: { code: code.trim().toUpperCase(), flat: flat.trim() } });
      Alert.alert("Request sent", "Your society manager will approve you. Society chargers then appear on your map.");
      setMode("none");
      void reload();
    } catch (e) {
      Alert.alert("Couldn't join", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function create() {
    setBusy(true);
    try {
      await api("/communities", { body: { name: name.trim(), address: address.trim(), manager_flat: flat.trim() } });
      Alert.alert("Society submitted", "ChargeShare will verify it (usually within a day). Then you'll get a join code to share with residents.");
      setMode("none");
      void reload();
    } catch (e) {
      Alert.alert("Couldn't create", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (loading && !data) return <Loading />;
  const tone = (s: string) => (s === "approved" ? "green" : s === "pending" ? "amber" : "red");

  return (
    <Screen onRefresh={reload} refreshing={loading}>
      <Notice
        icon="business-outline"
        text="Share chargers safely inside your apartment complex. Only approved residents see society chargers, and the manager gets a monthly per-flat usage statement for fair cost-sharing."
      />
      {data?.map((c) => (
        <Card key={c.id} onPress={c.role === "manager" ? () => router.push(`/society/${c.id}`) : undefined}>
          <Row style={{ justifyContent: "space-between" }}>
            <Text style={{ fontSize: 16, fontWeight: "700", color: colors.text, flex: 1 }}>{c.name}</Text>
            <Badge label={c.role === "manager" ? `Manager · ${c.status}` : c.my_status || "pending"} tone={tone(c.role === "manager" ? c.status : c.my_status)} />
          </Row>
          <Small>{c.address}</Small>
          <Small>
            {c.members_count} residents · {c.chargers_count} chargers
            {c.role === "manager" && c.status === "approved" ? ` · Join code ${c.code}` : ""}
          </Small>
          {c.role === "manager" ? <Small style={{ color: colors.primaryDark }}>Manage residents and statements ›</Small> : null}
        </Card>
      ))}
      {data?.length === 0 && <Body muted>You're not part of a housing society on ChargeShare yet.</Body>}

      {mode === "none" && (
        <>
          <Button title="Join my society" icon="enter-outline" onPress={() => setMode("join")} />
          <Button title="Register my society (for RWA / manager)" variant="secondary" onPress={() => setMode("create")} />
        </>
      )}
      {mode === "join" && (
        <Card>
          <H2>Join with a code</H2>
          <Field label="Society join code" value={code} onChangeText={setCode} autoCapitalize="characters" placeholder="e.g. LAKE01" />
          <Field label="Your flat / unit number" value={flat} onChangeText={setFlat} placeholder="e.g. C-803" />
          <Button title="Send request" onPress={join} loading={busy} disabled={code.length < 4 || !flat} />
          <Button title="Cancel" variant="ghost" onPress={() => setMode("none")} />
        </Card>
      )}
      {mode === "create" && (
        <Card>
          <H2>Register your society</H2>
          <Field label="Society name" value={name} onChangeText={setName} placeholder="e.g. Lake View Residency" />
          <Field label="Address" value={address} onChangeText={setAddress} placeholder="Area, city" />
          <Field label="Your flat / unit number" value={flat} onChangeText={setFlat} placeholder="e.g. A-101" />
          <Button title="Submit for verification" onPress={create} loading={busy} disabled={name.length < 3 || address.length < 5 || !flat} />
          <Button title="Cancel" variant="ghost" onPress={() => setMode("none")} />
        </Card>
      )}
    </Screen>
  );
}
