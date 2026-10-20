"""App settings. Every value can be set with an environment variable or a .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- core ---
    app_name: str = "ChargeShare"
    environment: str = "development"  # development | production
    database_url: str = "sqlite:///./chargeshare.db"
    jwt_secret: str = "change-me-in-production"
    jwt_days: int = 30
    public_base_url: str = "http://localhost:8000"  # where this API is reachable from phones
    app_scheme: str = "chargeshare"  # deep link scheme of the mobile app
    cors_origins: str = "*"  # comma separated; set to the admin panel URL in production

    # --- business rules ---
    commission_percent: float = 10.0
    min_booking_minutes: int = 30
    max_booking_minutes: int = 8 * 60
    max_days_ahead: int = 14
    free_cancel_minutes: int = 60  # cancel at least this long before start = full refund
    late_cancel_refund_percent: int = 50
    payment_window_minutes: int = 15  # unpaid bookings are released after this
    checkin_early_minutes: int = 15
    auto_complete_after_minutes: int = 30
    local_timezone: str = "Asia/Kolkata"

    # --- admin bootstrap: these phone numbers become admins on first login ---
    admin_phones: str = ""  # e.g. "+919876543210,+919812345678"

    # --- OTP / SMS ---
    otp_provider: str = "console"  # console | msg91
    msg91_auth_key: str = ""
    msg91_template_id: str = ""
    demo_phone: str = ""  # a fixed number + OTP for App Store / Play Store reviewers
    demo_otp: str = ""

    # --- payments ---
    payment_provider: str = "mock"  # mock | razorpay
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # --- file storage ---
    storage_backend: str = "local"  # local | supabase
    local_upload_dir: str = "./uploads"
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_public_bucket: str = "public-media"
    supabase_private_bucket: str = "private-docs"
    max_upload_mb: int = 8

    # --- push notifications (Expo push service) ---
    push_enabled: bool = True
    expo_access_token: str = ""

    @property
    def admin_phone_list(self) -> list[str]:
        return [p.strip() for p in self.admin_phones.split(",") if p.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
