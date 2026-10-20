import type { ExpoConfig } from "expo/config";

// Values come from mobile/.env (see .env.example) or from EAS environment variables.
const APP_NAME = process.env.APP_NAME ?? "ChargeShare";
const BUNDLE_ID = process.env.APP_BUNDLE_ID ?? "com.chargeshare.app";
const EAS_PROJECT_ID = process.env.EAS_PROJECT_ID ?? "";

const config: ExpoConfig = {
  name: APP_NAME,
  slug: "chargeshare",
  scheme: "chargeshare",
  version: "1.0.0",
  orientation: "portrait",
  icon: "./assets/icon.png",
  userInterfaceStyle: "light",
  ios: {
    bundleIdentifier: BUNDLE_ID,
    buildNumber: "1",
    supportsTablet: false,
    infoPlist: {
      NSLocationWhenInUseUsageDescription:
        "ChargeShare uses your location to show EV chargers near you and to place your own charger on the map.",
      NSCameraUsageDescription: "ChargeShare uses the camera to scan the QR code on a charger when you arrive.",
      NSPhotoLibraryUsageDescription: "ChargeShare lets you add photos of your charger and your ID proof.",
      ITSAppUsesNonExemptEncryption: false,
    },
  },
  android: {
    package: BUNDLE_ID,
    versionCode: 1,
    adaptiveIcon: { foregroundImage: "./assets/adaptive-icon.png", backgroundColor: "#0F9D58" },
    permissions: ["ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION", "CAMERA"],
    config: { googleMaps: { apiKey: process.env.GOOGLE_MAPS_ANDROID_KEY ?? "" } },
  },
  plugins: [
    "expo-router",
    "expo-secure-store",
    [
      "expo-location",
      {
        locationWhenInUsePermission:
          "ChargeShare uses your location to show EV chargers near you and to place your own charger on the map.",
      },
    ],
    ["expo-camera", { cameraPermission: "ChargeShare uses the camera to scan the QR code on a charger when you arrive." }],
    ["expo-image-picker", { photosPermission: "ChargeShare lets you add photos of your charger and your ID proof." }],
    ["expo-notifications", { color: "#0F9D58" }],
  ],
  experiments: { typedRoutes: false },
  extra: {
    eas: EAS_PROJECT_ID ? { projectId: EAS_PROJECT_ID } : undefined,
  },
};

export default config;
