import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { useState } from "react";
import { Alert, Linking, Text, View } from "react-native";

import { api, API_URL } from "../src/api";
import { colors, space } from "../src/theme";
import { Body, Button, Field, H1, Screen, Small } from "../src/ui";

export default function Login() {
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);

  async function send() {
    setBusy(true);
    try {
      const res = await api<{ phone: string }>("/auth/otp/request", { body: { phone } });
      router.push({ pathname: "/verify", params: { phone: res.phone } });
    } catch (e) {
      Alert.alert("Couldn't send OTP", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen edges={["top", "bottom"]}>
      <View style={{ alignItems: "center", marginTop: space.xxl, gap: space.md }}>
        <View style={{ backgroundColor: colors.primary, borderRadius: 24, padding: 18 }}>
          <Ionicons name="flash" size={44} color="#fff" />
        </View>
        <H1>ChargeShare</H1>
        <Body muted style={{ textAlign: "center" }}>
          Charge your EV at a neighbour's charger.{"\n"}Or earn from yours when it's free.
        </Body>
      </View>
      <View style={{ marginTop: space.xxl, gap: space.lg }}>
        <Field
          label="Mobile number"
          placeholder="98765 43210"
          keyboardType="phone-pad"
          maxLength={14}
          value={phone}
          onChangeText={setPhone}
          autoFocus
        />
        <Button title="Send OTP" onPress={send} loading={busy} disabled={phone.replace(/\D/g, "").length < 10} />
        <Small style={{ textAlign: "center" }}>
          By continuing you agree to our{" "}
          <Text style={{ color: colors.primaryDark }} onPress={() => Linking.openURL(`${API_URL}/legal/terms`)}>
            Terms
          </Text>{" "}
          and{" "}
          <Text style={{ color: colors.primaryDark }} onPress={() => Linking.openURL(`${API_URL}/legal/privacy`)}>
            Privacy Policy
          </Text>
          .
        </Small>
      </View>
    </Screen>
  );
}
