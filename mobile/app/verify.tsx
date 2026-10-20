import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Alert } from "react-native";

import { api } from "../src/api";
import { useAuth } from "../src/auth";
import type { User } from "../src/types";
import { Body, Button, Field, Screen } from "../src/ui";

export default function Verify() {
  const { phone } = useLocalSearchParams<{ phone: string }>();
  const { signIn } = useAuth();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);

  async function verify() {
    setBusy(true);
    try {
      const res = await api<{ token: string; user: User }>("/auth/otp/verify", { body: { phone, code } });
      await signIn(res.token, res.user);
      router.replace(res.user.name ? "/(tabs)" : "/onboarding");
    } catch (e) {
      Alert.alert("Couldn't verify", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    try {
      await api("/auth/otp/request", { body: { phone } });
      Alert.alert("OTP sent", "Check your messages.");
    } catch (e) {
      Alert.alert("Couldn't resend", (e as Error).message);
    }
  }

  return (
    <Screen>
      <Body muted>Enter the 6-digit code sent to {phone}.</Body>
      <Field label="OTP" value={code} onChangeText={setCode} keyboardType="number-pad" maxLength={6} autoFocus textContentType="oneTimeCode" autoComplete="sms-otp" />
      <Button title="Verify and continue" onPress={verify} loading={busy} disabled={code.length < 4} />
      <Button title="Resend OTP" variant="ghost" onPress={resend} />
    </Screen>
  );
}
