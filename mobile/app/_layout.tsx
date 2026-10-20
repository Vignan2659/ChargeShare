import * as Notifications from "expo-notifications";
import { router, Stack, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AuthProvider, useAuth } from "../src/auth";
import { registerForPush } from "../src/push";
import { colors } from "../src/theme";

function PushSetup() {
  const { user, ready } = useAuth();
  const segments = useSegments();
  const first = segments[0] as string | undefined;

  // logged out (or session expired) anywhere inside the app -> back to login
  useEffect(() => {
    if (ready && !user && first && first !== "login" && first !== "verify") router.replace("/login");
  }, [ready, user, first]);

  useEffect(() => {
    if (!user) return;
    void registerForPush();
    // tapping a notification opens the booking it is about
    const sub = Notifications.addNotificationResponseReceivedListener((resp) => {
      const data = resp.notification.request.content.data ?? {};
      if (data.bookingId) router.push(`/booking/${data.bookingId}`);
      else if (data.chargerId) router.push(`/charger/${data.chargerId}`);
    });
    return () => sub.remove();
  }, [user?.id]);
  return null;
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <StatusBar style="dark" />
        <PushSetup />
        <Stack
          screenOptions={{
            headerTintColor: colors.text,
            headerStyle: { backgroundColor: "#fff" },
            headerTitleStyle: { fontWeight: "700" },
            contentStyle: { backgroundColor: colors.bg },
            headerBackTitle: "Back",
          }}
        >
          <Stack.Screen name="index" options={{ headerShown: false }} />
          <Stack.Screen name="login" options={{ headerShown: false }} />
          <Stack.Screen name="verify" options={{ title: "Verify number" }} />
          <Stack.Screen name="onboarding" options={{ title: "About you", headerBackVisible: false }} />
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="charger/[id]" options={{ title: "Charger" }} />
          <Stack.Screen name="book/[id]" options={{ title: "Book a slot" }} />
          <Stack.Screen name="pay" options={{ title: "Payment", presentation: "modal" }} />
          <Stack.Screen name="booking/[id]" options={{ title: "Booking" }} />
          <Stack.Screen name="scan/[id]" options={{ title: "Scan charger QR" }} />
          <Stack.Screen name="review/[id]" options={{ title: "Rate your session", presentation: "modal" }} />
          <Stack.Screen name="report" options={{ title: "Report a problem", presentation: "modal" }} />
          <Stack.Screen name="host/apply" options={{ title: "Become a host" }} />
          <Stack.Screen name="host/charger-form" options={{ title: "Charger details" }} />
          <Stack.Screen name="host/charger/[id]" options={{ title: "Manage charger" }} />
          <Stack.Screen name="host/earnings" options={{ title: "Earnings" }} />
          <Stack.Screen name="profile-edit" options={{ title: "Edit profile" }} />
          <Stack.Screen name="dues" options={{ title: "Pending dues" }} />
          <Stack.Screen name="society/index" options={{ title: "Housing society" }} />
          <Stack.Screen name="society/[id]" options={{ title: "Manage society" }} />
        </Stack>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
