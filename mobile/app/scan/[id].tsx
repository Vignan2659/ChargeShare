import { CameraView, useCameraPermissions } from "expo-camera";
import { router, useLocalSearchParams } from "expo-router";
import { useRef, useState } from "react";
import { Alert, StyleSheet, View } from "react-native";

import { api } from "../../src/api";
import { space } from "../../src/theme";
import { Body, Button, Field, Screen } from "../../src/ui";

const PREFIX = "chargeshare:qr:";

export default function Scan() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [permission, requestPermission] = useCameraPermissions();
  const [manual, setManual] = useState("");
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);

  async function checkIn(raw: string) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    const token = raw.startsWith(PREFIX) ? raw.slice(PREFIX.length) : raw.trim();
    try {
      await api(`/bookings/${id}/check-in`, { body: { qr_token: token } });
      Alert.alert("Charging started", "Plug in your vehicle. Finish the session in the app when you're done.");
      router.back();
    } catch (e) {
      Alert.alert("Check-in failed", (e as Error).message, [{ text: "OK", onPress: () => (locked.current = false) }]);
    } finally {
      setBusy(false);
    }
  }

  if (!permission) return <View />;
  if (!permission.granted) {
    return (
      <Screen>
        <Body>We need the camera to scan the QR code stuck on the charger.</Body>
        <Button title="Allow camera" onPress={requestPermission} />
        <Field label="Or type the code under the QR" value={manual} onChangeText={setManual} autoCapitalize="none" />
        <Button title="Check in" variant="secondary" onPress={() => checkIn(manual)} disabled={!manual} loading={busy} />
      </Screen>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      <CameraView
        style={StyleSheet.absoluteFill}
        facing="back"
        barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
        onBarcodeScanned={({ data }) => void checkIn(data)}
      />
      <View style={styles.frame} />
      <View style={styles.bottom}>
        <Field label="Can't scan? Type the code" value={manual} onChangeText={setManual} autoCapitalize="none" />
        <Button title="Check in with code" variant="secondary" onPress={() => checkIn(manual)} disabled={!manual} loading={busy} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { position: "absolute", top: "22%", alignSelf: "center", width: 240, height: 240, borderWidth: 3, borderColor: "#fff", borderRadius: 16 },
  bottom: { position: "absolute", left: 0, right: 0, bottom: 0, padding: space.lg, gap: space.sm, backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16 },
});
