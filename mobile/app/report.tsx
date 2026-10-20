import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Alert } from "react-native";

import { api } from "../src/api";
import { Body, Button, ChipGroup, Field, Notice, Screen } from "../src/ui";

const CATEGORIES = [
  { label: "Charger not working", value: "charger" },
  { label: "Payment / refund", value: "payment" },
  { label: "Safety", value: "safety" },
  { label: "Host / driver behaviour", value: "behaviour" },
  { label: "Other", value: "other" },
];

export default function Report() {
  const { bookingId, chargerId } = useLocalSearchParams<{ bookingId?: string; chargerId?: string }>();
  const [category, setCategory] = useState("other");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      await api("/reports", {
        body: {
          category,
          message: message.trim(),
          booking_id: bookingId ? Number(bookingId) : null,
          charger_id: chargerId ? Number(chargerId) : null,
        },
      });
      Alert.alert("Report sent", "Our team will look into it and get back to you.");
      router.back();
    } catch (e) {
      Alert.alert("Couldn't send", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      {category === "safety" && <Notice tone="red" icon="warning" text="If anyone is in danger, call 112 first." />}
      <Body>What went wrong?</Body>
      <ChipGroup options={CATEGORIES} value={category} onChange={(v) => setCategory(v as string)} />
      <Field label="Details" value={message} onChangeText={setMessage} multiline maxLength={3000} placeholder="Tell us what happened" />
      <Button title="Send report" onPress={submit} loading={busy} disabled={message.trim().length < 5} />
    </Screen>
  );
}
