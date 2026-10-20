import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { Alert, Linking, Pressable, Text } from "react-native";

import { api, API_URL } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, space } from "../../src/theme";
import { Badge, Card, Divider, H2, Row, Screen, Small } from "../../src/ui";

const SUPPORT = process.env.EXPO_PUBLIC_SUPPORT_EMAIL ?? "";

function Item({ icon, label, onPress, danger }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void; danger?: boolean }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [{ flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: 12 }, pressed && { opacity: 0.6 }]}>
      <Ionicons name={icon} size={22} color={danger ? colors.danger : colors.muted} />
      <Text style={{ flex: 1, fontSize: 16, color: danger ? colors.danger : colors.text }}>{label}</Text>
      <Ionicons name="chevron-forward" size={18} color={colors.border} />
    </Pressable>
  );
}

export default function Profile() {
  const { user, signOut } = useAuth();
  if (!user) return null;

  function deleteAccount() {
    Alert.alert(
      "Delete account?",
      "This cancels your open bookings (with refunds), removes your chargers and personal details. It can't be undone.",
      [
        { text: "Keep account", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            try {
              await api("/me", { method: "DELETE" });
              await signOut();
            } catch (e) {
              Alert.alert("Couldn't delete", (e as Error).message);
            }
          },
        },
      ],
    );
  }

  const hostLabel = { none: "Not a host", pending: "Host: in review", approved: "Verified host", rejected: "Host: not approved" }[user.host_status];

  return (
    <Screen>
      <Card>
        <H2>{user.name || "Your profile"}</H2>
        <Small>{user.phone}</Small>
        <Row>
          <Badge label={hostLabel} tone={user.host_status === "approved" ? "green" : "grey"} />
          {user.vehicle_type ? <Badge label={user.vehicle_type === "2W" ? "Scooter" : user.vehicle_type === "3W" ? "Auto" : "Car"} tone="blue" /> : null}
        </Row>
      </Card>
      <Card>
        <Item icon="create-outline" label="Edit profile" onPress={() => router.push("/profile-edit")} />
        <Divider />
        <Item icon="wallet-outline" label="Earnings and payouts" onPress={() => router.push("/host/earnings")} />
        <Divider />
        <Item icon="alert-circle-outline" label="Report a problem" onPress={() => router.push("/report")} />
        {SUPPORT ? (
          <>
            <Divider />
            <Item icon="mail-outline" label="Contact support" onPress={() => Linking.openURL(`mailto:${SUPPORT}`)} />
          </>
        ) : null}
      </Card>
      <Card>
        <Item icon="document-text-outline" label="Terms of use" onPress={() => Linking.openURL(`${API_URL}/legal/terms`)} />
        <Divider />
        <Item icon="shield-checkmark-outline" label="Privacy policy" onPress={() => Linking.openURL(`${API_URL}/legal/privacy`)} />
      </Card>
      <Card>
        <Item icon="log-out-outline" label="Log out" onPress={() => void signOut()} />
        <Divider />
        <Item icon="trash-outline" label="Delete my account" onPress={deleteAccount} danger />
      </Card>
      <Small style={{ textAlign: "center" }}>ChargeShare v1.0.0</Small>
    </Screen>
  );
}
