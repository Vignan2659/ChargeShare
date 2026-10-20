export type User = {
  id: number;
  phone: string;
  name: string;
  email: string;
  is_admin: boolean;
  is_host: boolean;
  host_status: "none" | "pending" | "approved" | "rejected";
  host_note: string;
  payout_upi: string;
  vehicle_type: "" | "2W" | "3W" | "4W";
  created_at: string;
};

export type Charger = {
  id: number;
  host_id: number;
  title: string;
  description: string;
  address: string;
  lat: number;
  lng: number;
  vehicle_types: string[];
  connector_type: string;
  power_kw: number;
  pricing_mode: "hour" | "kwh";
  price_paise: number;
  photo_urls: string[];
  open_time: string;
  close_time: string;
  auto_accept: boolean;
  society_only: boolean;
  society_name: string;
  safety_checked: boolean;
  status: "pending" | "approved" | "rejected" | "paused" | "removed";
  distance_km: number | null;
  rating_avg: number | null;
  rating_count: number;
  host_name: string;
};

export type HostCharger = Charger & {
  access_notes: string;
  has_society_noc: boolean;
  admin_note: string;
  qr_token: string;
  created_at: string;
};

export type Review = { id: number; rating: number; comment: string; created_at: string; author_name: string };
export type BusySlot = { start_at: string; end_at: string };
export type ChargerDetail = Charger & { busy: BusySlot[]; reviews: Review[] };

export type BookingStatus =
  | "pending_payment"
  | "requested"
  | "confirmed"
  | "active"
  | "completed"
  | "cancelled"
  | "declined"
  | "expired";

export type Booking = {
  id: number;
  charger_id: number;
  driver_id: number;
  host_id: number;
  start_at: string;
  end_at: string;
  vehicle_type: string;
  vehicle_note: string;
  status: BookingStatus;
  pricing_mode: "hour" | "kwh";
  unit_price_paise: number;
  amount_paise: number;
  final_amount_paise: number | null;
  refund_paise: number;
  commission_paise: number;
  host_earning_paise: number;
  kwh_used: number | null;
  no_show: boolean;
  cancel_reason: string;
  cancelled_by: string;
  created_at: string;
  checked_in_at: string | null;
  completed_at: string | null;
  charger: {
    id: number;
    title: string;
    address: string;
    lat: number;
    lng: number;
    connector_type: string;
    power_kw: number;
    photo_urls: string[];
  };
  other_party_name: string;
  other_party_phone: string;
  access_notes: string;
  can_review: boolean;
  payment_order_id: string;
};

export type Checkout = { booking: Booking; provider: "mock" | "razorpay"; checkout_url: string };

export type Earnings = {
  completed_sessions: number;
  total_earned_paise: number;
  this_month_paise: number;
  pending_payout_paise: number;
  paid_out_paise: number;
  upcoming_bookings: number;
};

export type Payout = {
  id: number;
  amount_paise: number;
  booking_count: number;
  upi_id: string;
  status: "pending" | "paid";
  reference: string;
  created_at: string;
  paid_at: string | null;
};
