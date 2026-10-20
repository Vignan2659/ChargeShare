import { Redirect } from "expo-router";

import { useAuth } from "../src/auth";
import { Loading } from "../src/ui";

export default function Index() {
  const { ready, user } = useAuth();
  if (!ready) return <Loading />;
  if (!user) return <Redirect href="/login" />;
  if (!user.name) return <Redirect href="/onboarding" />;
  return <Redirect href="/(tabs)" />;
}
