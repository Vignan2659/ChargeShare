import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState, type ReactNode } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, radius, space } from "./theme";

// ---------- layout ----------
export function Screen({
  children,
  scroll = true,
  onRefresh,
  refreshing = false,
  padded = true,
  edges = ["bottom"],
}: {
  children: ReactNode;
  scroll?: boolean;
  onRefresh?: () => void;
  refreshing?: boolean;
  padded?: boolean;
  edges?: ("top" | "bottom")[];
}) {
  const inner = padded ? { padding: space.lg, gap: space.md } : undefined;
  return (
    <SafeAreaView style={styles.screen} edges={edges}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        {scroll ? (
          <ScrollView
            contentContainerStyle={[inner, { paddingBottom: 48 }]}
            keyboardShouldPersistTaps="handled"
            refreshControl={onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} /> : undefined}
          >
            {children}
          </ScrollView>
        ) : (
          <View style={[{ flex: 1 }, inner]}>{children}</View>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export function Card({ children, style, onPress }: { children: ReactNode; style?: ViewStyle; onPress?: () => void }) {
  if (onPress) {
    return (
      <Pressable onPress={onPress} style={({ pressed }) => [styles.card, style, pressed && { opacity: 0.85 }]}>
        {children}
      </Pressable>
    );
  }
  return <View style={[styles.card, style]}>{children}</View>;
}

export const Row = ({ children, style }: { children: ReactNode; style?: ViewStyle }) => (
  <View style={[{ flexDirection: "row", alignItems: "center", gap: space.sm }, style]}>{children}</View>
);

// ---------- text ----------
export const H1 = ({ children }: { children: ReactNode }) => <Text style={styles.h1}>{children}</Text>;
export const H2 = ({ children }: { children: ReactNode }) => <Text style={styles.h2}>{children}</Text>;
export const Body = ({ children, muted, style }: { children: ReactNode; muted?: boolean; style?: object }) => (
  <Text style={[styles.body, muted && { color: colors.muted }, style]}>{children}</Text>
);
export const Small = ({ children, style }: { children: ReactNode; style?: object }) => (
  <Text style={[styles.small, style]}>{children}</Text>
);

// ---------- controls ----------
export function Button({
  title,
  onPress,
  variant = "primary",
  loading = false,
  disabled = false,
  icon,
  style,
}: {
  title: string;
  onPress: () => void | Promise<void>;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  loading?: boolean;
  disabled?: boolean;
  icon?: keyof typeof Ionicons.glyphMap;
  style?: ViewStyle;
}) {
  const v = buttonVariants[variant];
  const off = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={off ? undefined : onPress}
      style={({ pressed }) => [styles.button, v.box, off && { opacity: 0.5 }, pressed && !off && { opacity: 0.8 }, style]}
    >
      {loading ? (
        <ActivityIndicator color={v.text.color} />
      ) : (
        <Row style={{ justifyContent: "center" }}>
          {icon && <Ionicons name={icon} size={18} color={v.text.color} />}
          <Text style={[styles.buttonText, v.text]}>{title}</Text>
        </Row>
      )}
    </Pressable>
  );
}

const buttonVariants = {
  primary: { box: { backgroundColor: colors.primary }, text: { color: "#fff" } },
  secondary: { box: { backgroundColor: colors.primarySoft }, text: { color: colors.primaryDark } },
  danger: { box: { backgroundColor: colors.dangerSoft }, text: { color: colors.danger } },
  ghost: { box: { backgroundColor: "transparent" }, text: { color: colors.primaryDark } },
};

export function Field({ label, hint, ...props }: TextInputProps & { label: string; hint?: string }) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput placeholderTextColor="#9AA4AE" style={[styles.input, props.multiline && { minHeight: 90, textAlignVertical: "top" }]} {...props} />
      {hint ? <Small>{hint}</Small> : null}
    </View>
  );
}

export function Chip({ label, selected, onPress }: { label: string; selected?: boolean; onPress?: () => void }) {
  return (
    <Pressable onPress={onPress} style={[styles.chip, selected && { backgroundColor: colors.primary, borderColor: colors.primary }]}>
      <Text style={[styles.chipText, selected && { color: "#fff" }]}>{label}</Text>
    </Pressable>
  );
}

export function ChipGroup<T extends string>({
  options,
  value,
  onChange,
  multi = false,
}: {
  options: { label: string; value: T }[];
  value: T | T[];
  onChange: (v: T | T[]) => void;
  multi?: boolean;
}) {
  const selected = (v: T) => (Array.isArray(value) ? value.includes(v) : value === v);
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space.sm }}>
      {options.map((o) => (
        <Chip
          key={o.value}
          label={o.label}
          selected={selected(o.value)}
          onPress={() => {
            if (!multi) return onChange(o.value);
            const arr = Array.isArray(value) ? value : [];
            onChange(arr.includes(o.value) ? arr.filter((x) => x !== o.value) : [...arr, o.value]);
          }}
        />
      ))}
    </View>
  );
}

export function Toggle({ label, value, onChange, hint }: { label: string; value: boolean; onChange: (v: boolean) => void; hint?: string }) {
  return (
    <Pressable onPress={() => onChange(!value)} style={{ flexDirection: "row", gap: space.md, alignItems: "flex-start" }}>
      <Ionicons name={value ? "checkbox" : "square-outline"} size={24} color={value ? colors.primary : colors.muted} />
      <View style={{ flex: 1 }}>
        <Body>{label}</Body>
        {hint ? <Small>{hint}</Small> : null}
      </View>
    </Pressable>
  );
}

const TONES = {
  green: { bg: colors.primarySoft, fg: colors.primaryDark },
  amber: { bg: colors.warningSoft, fg: colors.warning },
  red: { bg: colors.dangerSoft, fg: colors.danger },
  blue: { bg: colors.infoSoft, fg: colors.info },
  grey: { bg: "#EEF1F3", fg: colors.muted },
};

export function Badge({ label, tone = "grey" }: { label: string; tone?: keyof typeof TONES }) {
  return (
    <View style={[styles.badge, { backgroundColor: TONES[tone].bg }]}>
      <Text style={{ color: TONES[tone].fg, fontSize: 12, fontWeight: "600" }}>{label}</Text>
    </View>
  );
}

export function Notice({ text, tone = "blue", icon = "information-circle" }: { text: string; tone?: keyof typeof TONES; icon?: keyof typeof Ionicons.glyphMap }) {
  return (
    <View style={[styles.notice, { backgroundColor: TONES[tone].bg }]}>
      <Ionicons name={icon} size={20} color={TONES[tone].fg} />
      <Text style={{ color: TONES[tone].fg, flex: 1, lineHeight: 20 }}>{text}</Text>
    </View>
  );
}

export function Empty({ icon = "flash-outline", title, text, action }: { icon?: keyof typeof Ionicons.glyphMap; title: string; text?: string; action?: ReactNode }) {
  return (
    <View style={{ alignItems: "center", padding: space.xxl, gap: space.sm }}>
      <Ionicons name={icon} size={44} color={colors.muted} />
      <H2>{title}</H2>
      {text ? <Body muted style={{ textAlign: "center" }}>{text}</Body> : null}
      {action}
    </View>
  );
}

export const Loading = () => (
  <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: space.xxl }}>
    <ActivityIndicator size="large" color={colors.primary} />
  </View>
);

export function Stars({ value, size = 14 }: { value: number | null; size?: number }) {
  if (value == null) return <Small>No ratings yet</Small>;
  return (
    <Row style={{ gap: 2 }}>
      <Ionicons name="star" size={size} color="#F4B400" />
      <Text style={{ fontSize: size, fontWeight: "600", color: colors.text }}>{value.toFixed(1)}</Text>
    </Row>
  );
}

export const Divider = () => <View style={{ height: 1, backgroundColor: colors.border, marginVertical: space.sm }} />;

export function InfoRow({ icon, text }: { icon: keyof typeof Ionicons.glyphMap; text: string }) {
  return (
    <Row>
      <Ionicons name={icon} size={18} color={colors.muted} />
      <Body style={{ flex: 1 }}>{text}</Body>
    </Row>
  );
}

// ---------- data hook ----------
/** Loads data when the screen gains focus; returns {data, error, loading, reload}. */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await loaderRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useFocusEffect(
    useCallback(() => {
      void reload();
    }, [reload]),
  );
  return { data, error, loading, reload, setData };
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    padding: space.lg,
    gap: space.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  h1: { fontSize: 26, fontWeight: "700", color: colors.text },
  h2: { fontSize: 18, fontWeight: "700", color: colors.text },
  body: { fontSize: 15, color: colors.text, lineHeight: 21 },
  small: { fontSize: 13, color: colors.muted, lineHeight: 18 },
  label: { fontSize: 14, fontWeight: "600", color: colors.text },
  input: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingVertical: 12,
    fontSize: 16,
    color: colors.text,
  },
  button: { borderRadius: radius.md, paddingVertical: 14, paddingHorizontal: space.lg, alignItems: "center", minHeight: 50, justifyContent: "center" },
  buttonText: { fontSize: 16, fontWeight: "700" },
  chip: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#fff",
    borderRadius: radius.pill,
    paddingVertical: 8,
    paddingHorizontal: 14,
  },
  chipText: { fontSize: 14, color: colors.text, fontWeight: "500" },
  badge: { borderRadius: radius.pill, paddingVertical: 3, paddingHorizontal: 10, alignSelf: "flex-start" },
  notice: { flexDirection: "row", gap: space.sm, padding: space.md, borderRadius: radius.md, alignItems: "flex-start" },
});
