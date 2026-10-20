import { api } from "../../src/api";
import { useAuth } from "../../src/auth";
import { dayLabel, parseUtc, rupees } from "../../src/format";
import type { Booking, Earnings, Payout } from "../../src/types";
import { Badge, Body, Card, Divider, H2, Loading, Notice, Row, Screen, Small, useLoad } from "../../src/ui";
import { BookingRow } from "../../src/BookingRow";

export default function EarningsScreen() {
  const { user } = useAuth();
  const { data, loading, reload } = useLoad(async () => {
    const [earnings, payouts, past] = await Promise.all([
      api<Earnings>("/me/earnings"),
      api<Payout[]>("/me/payouts"),
      api<Booking[]>("/bookings?role=host&scope=past"),
    ]);
    return { earnings, payouts, past: past.filter((b) => b.host_earning_paise > 0) };
  });

  if (loading && !data) return <Loading />;
  if (!data) return null;
  const e = data.earnings;

  return (
    <Screen onRefresh={reload} refreshing={loading}>
      <Card>
        <Row style={{ justifyContent: "space-between" }}>
          <Body>Total earned</Body>
          <H2>{rupees(e.total_earned_paise)}</H2>
        </Row>
        <Divider />
        <Row style={{ justifyContent: "space-between" }}>
          <Small>This month</Small>
          <Body>{rupees(e.this_month_paise)}</Body>
        </Row>
        <Row style={{ justifyContent: "space-between" }}>
          <Small>Waiting to be paid</Small>
          <Body>{rupees(e.pending_payout_paise)}</Body>
        </Row>
        <Row style={{ justifyContent: "space-between" }}>
          <Small>Already paid to you</Small>
          <Body>{rupees(e.paid_out_paise)}</Body>
        </Row>
        <Row style={{ justifyContent: "space-between" }}>
          <Small>Sessions completed</Small>
          <Body>{e.completed_sessions}</Body>
        </Row>
      </Card>
      <Notice text={`Payouts go every week to ${user?.payout_upi || "your UPI ID"}. Earnings are after the 10% service fee.`} />

      <H2>Payouts</H2>
      {data.payouts.length === 0 ? (
        <Small>No payouts yet.</Small>
      ) : (
        data.payouts.map((p) => (
          <Card key={p.id}>
            <Row style={{ justifyContent: "space-between" }}>
              <H2>{rupees(p.amount_paise)}</H2>
              <Badge label={p.status === "paid" ? "Paid" : "Processing"} tone={p.status === "paid" ? "green" : "amber"} />
            </Row>
            <Small>
              {p.booking_count} sessions · {dayLabel(parseUtc(p.paid_at ?? p.created_at))}
              {p.reference ? ` · Ref ${p.reference}` : ""}
            </Small>
          </Card>
        ))
      )}

      <H2>Recent sessions</H2>
      {data.past.length === 0 ? <Small>No completed sessions yet.</Small> : data.past.slice(0, 30).map((b) => <BookingRow key={b.id} b={b} showEarning />)}
    </Screen>
  );
}
