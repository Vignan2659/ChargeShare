import { router, useLocalSearchParams } from "expo-router";
import { useRef, useState } from "react";
import { Alert, Linking, View } from "react-native";
import { WebView, type WebViewNavigation } from "react-native-webview";

import { api } from "../src/api";
import { rupees } from "../src/format";
import { space } from "../src/theme";
import type { Booking } from "../src/types";
import { Body, Button, H2, Loading, Notice, Screen } from "../src/ui";

/** Razorpay checkout runs inside a WebView page served by our backend. When it finishes, the page
 * navigates to chargeshare://payment-result?... which we catch here. Test mode shows a simple button. */
export default function Pay() {
  const { bookingId, provider, url, amount } = useLocalSearchParams<{ bookingId: string; provider: string; url: string; amount: string }>();
  const [busy, setBusy] = useState(false);
  const handled = useRef(false);

  async function finish(status: string) {
    if (handled.current) return;
    handled.current = true;
    try {
      const b = await api<Booking>(`/payments/${bookingId}/sync`, { method: "POST" });
      if (b.status === "pending_payment") {
        Alert.alert(
          status === "cancelled" ? "Payment cancelled" : "Payment not completed",
          "Your slot is held for 15 minutes. Open the booking to try again.",
        );
      }
    } catch {
      // ignore: the booking screen will show the latest status
    }
    router.replace(`/booking/${bookingId}`);
  }

  async function mockPay() {
    setBusy(true);
    try {
      await api(`/payments/${bookingId}/mock-pay`, { method: "POST" });
      router.replace(`/booking/${bookingId}`);
    } catch (e) {
      Alert.alert("Payment failed", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (provider !== "razorpay" || !url) {
    return (
      <Screen>
        <H2>Test payment</H2>
        <Notice tone="amber" text="The server is in test mode (PAYMENT_PROVIDER=mock). No real money moves." />
        <Body>Amount: {rupees(Number(amount), 2)}</Body>
        <Button title="Pay (test)" onPress={mockPay} loading={busy} />
        <Button title="Cancel" variant="ghost" onPress={() => router.replace(`/booking/${bookingId}`)} />
      </Screen>
    );
  }

  const intercept = (req: WebViewNavigation) => {
    if (req.url.startsWith("chargeshare://payment-result")) {
      const status = /[?&]status=([a-z]+)/.exec(req.url)?.[1] ?? "pending";
      void finish(status);
      return false;
    }
    // UPI apps (upi://, intent://, tez://, phonepe://, paytmmp://) must open outside the WebView
    if (!/^(https?|about|data|blob):/.test(req.url)) {
      Linking.openURL(req.url).catch(() => Alert.alert("App not found", "Install a UPI app or choose another payment method."));
      return false;
    }
    return true;
  };

  return (
    <View style={{ flex: 1 }}>
      <WebView
        source={{ uri: url }}
        onShouldStartLoadWithRequest={intercept}
        startInLoadingState
        renderLoading={() => <Loading />}
        javaScriptEnabled
        domStorageEnabled
        setSupportMultipleWindows={false}
        originWhitelist={["*"]}
      />
      <View style={{ padding: space.md }}>
        <Button title="I've paid / close" variant="secondary" onPress={() => finish("pending")} />
      </View>
    </View>
  );
}
