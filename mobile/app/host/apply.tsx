import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { router } from "expo-router";
import { useState } from "react";
import { Alert, View } from "react-native";

import { api, uploadImage } from "../../src/api";
import { useAuth } from "../../src/auth";
import { space } from "../../src/theme";
import type { User } from "../../src/types";
import { Body, Button, Field, H2, Notice, Row, Screen, Small } from "../../src/ui";

export default function Apply() {
  const { user, setUser } = useAuth();
  const [docs, setDocs] = useState<{ uri: string; key: string }[]>([]);
  const [upi, setUpi] = useState(user?.payout_upi ?? "");
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);

  async function addDoc(fromCamera: boolean) {
    const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], quality: 0.7 };
    const res = fromCamera ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
    if (res.canceled) return;
    setUploading(true);
    try {
      const up = await uploadImage(res.assets[0].uri, "id_doc");
      setDocs((d) => [...d, { uri: res.assets[0].uri, key: up.key }]);
    } catch (e) {
      Alert.alert("Upload failed", (e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function submit() {
    setBusy(true);
    try {
      const u = await api<User>("/me/host-application", { body: { id_doc_keys: docs.map((d) => d.key), payout_upi: upi.trim() } });
      setUser(u);
      Alert.alert("Application sent", "Now add your charger. We'll review both together.");
      router.replace("/host/charger-form");
    } catch (e) {
      Alert.alert("Couldn't submit", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <H2>1. ID proof</H2>
      <Body muted>A photo of your Aadhaar, PAN, driving licence or voter ID. Only our verification team can see it.</Body>
      <Notice text="Tip: for Aadhaar, you can cover the first 8 digits. We only need your name and photo." />
      <Row style={{ flexWrap: "wrap" }}>
        {docs.map((d) => (
          <Image key={d.key} source={{ uri: d.uri }} style={{ width: 96, height: 64, borderRadius: 8 }} />
        ))}
      </Row>
      <Row>
        <Button style={{ flex: 1 }} title="Take photo" icon="camera" variant="secondary" onPress={() => addDoc(true)} loading={uploading} />
        <Button style={{ flex: 1 }} title="From gallery" icon="images" variant="secondary" onPress={() => addDoc(false)} disabled={uploading} />
      </Row>

      <View style={{ height: space.md }} />
      <H2>2. Where should we send your earnings?</H2>
      <Field label="UPI ID" value={upi} onChangeText={setUpi} autoCapitalize="none" placeholder="yourname@okaxis" hint="Payouts are sent weekly to this UPI ID." />

      <Small>
        By applying you confirm the charger is installed safely by an electrician (proper earthing and an RCCB/trip switch) and that you have
        permission from your housing society to let others use it.
      </Small>
      <Button title="Submit application" onPress={submit} loading={busy} disabled={docs.length === 0 || upi.trim().length < 5} />
    </Screen>
  );
}
