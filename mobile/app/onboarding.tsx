import { router } from "expo-router";
import { useState } from "react";
import { Alert } from "react-native";

import { api } from "../src/api";
import { useAuth } from "../src/auth";
import type { User } from "../src/types";
import { Body, Button, ChipGroup, Field, H2, Screen } from "../src/ui";

type Vehicle = "" | "2W" | "3W" | "4W";

export default function Onboarding() {
  const { setUser } = useAuth();
  const [name, setName] = useState("");
  const [vehicle, setVehicle] = useState<Vehicle>("");
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      const u = await api<User>("/me", { method: "PATCH", body: { name: name.trim(), vehicle_type: vehicle } });
      setUser(u);
      router.replace("/(tabs)");
    } catch (e) {
      Alert.alert("Couldn't save", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <H2>Welcome! What should we call you?</H2>
      <Field label="Full name" value={name} onChangeText={setName} placeholder="Your name" autoFocus autoCapitalize="words" />
      <Body muted>What do you drive? (skip if you only want to share your charger)</Body>
      <ChipGroup<Vehicle>
        options={[
          { label: "Scooter / bike", value: "2W" },
          { label: "Auto (3W)", value: "3W" },
          { label: "Car", value: "4W" },
        ]}
        value={vehicle}
        onChange={(v) => setVehicle(v as Vehicle)}
      />
      <Button title="Continue" onPress={save} loading={busy} disabled={name.trim().length < 2} />
    </Screen>
  );
}
