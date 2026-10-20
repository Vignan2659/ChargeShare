import { Linking, Platform } from "react-native";

export function openDirections(lat: number, lng: number, label: string) {
  const url =
    Platform.OS === "ios"
      ? `http://maps.apple.com/?daddr=${lat},${lng}&q=${encodeURIComponent(label)}`
      : `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`;
  void Linking.openURL(url);
}

export function callNumber(phone: string) {
  void Linking.openURL(`tel:${phone}`);
}
