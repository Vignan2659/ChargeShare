import { router } from "expo-router";
import { useState } from "react";
import { Alert } from "react-native";

import { api } from "../src/api";
import { useAuth } from "../src/auth";
import type { User } from "../src/types";
import { Body, Button, ChipGroup, Field, Screen } from "../src/ui";

type Vehicle = "" | "2W" | "3W" | "4W";

export default function ProfileEdit() {
  const { user, setUser } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [vehicle, setVehicle] = useState<Vehicle>(user?.vehicle_type ?? "");
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      setUser(await api<User>("/me", { method: "PATCH", body: { name: name.trim(), email: email.trim(), vehicle_type: vehicle } }));
      router.back();
    } catch (e) {
      Alert.alert("Couldn't save", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Field label="Full name" value={name} onChangeText={setName} autoCapitalize="words" />
      <Field label="Email (for receipts, optional)" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" />
      <Body>Your vehicle</Body>
      <ChipGroup<Vehicle>
        options={[
          { label: "None", value: "" },
          { label: "Scooter / bike", value: "2W" },
          { label: "Auto", value: "3W" },
          { label: "Car", value: "4W" },
        ]}
        value={vehicle}
        onChange={(v) => setVehicle(v as Vehicle)}
      />
      <Button title="Save" onPress={save} loading={busy} disabled={name.trim().length < 2} />
    </Screen>
  );
}
