import { Ionicons } from "@expo/vector-icons";
import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Alert, Pressable } from "react-native";

import { api } from "../../src/api";
import { Body, Button, Field, Row, Screen } from "../../src/ui";

export default function ReviewScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      await api("/reviews", { body: { booking_id: Number(id), rating, comment } });
      Alert.alert("Thanks!", "Your rating helps the community.");
      router.back();
    } catch (e) {
      Alert.alert("Couldn't submit", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Body>How was it?</Body>
      <Row style={{ justifyContent: "center", gap: 12, marginVertical: 12 }}>
        {[1, 2, 3, 4, 5].map((n) => (
          <Pressable key={n} onPress={() => setRating(n)} hitSlop={8}>
            <Ionicons name={n <= rating ? "star" : "star-outline"} size={40} color="#F4B400" />
          </Pressable>
        ))}
      </Row>
      <Field label="Comment (optional)" value={comment} onChangeText={setComment} multiline maxLength={1000} placeholder="Easy to find? Charger worked well?" />
      <Button title="Submit" onPress={submit} loading={busy} disabled={rating === 0} />
    </Screen>
  );
}
