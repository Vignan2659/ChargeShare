# ChargeShare: share and book EV chargers

ChargeShare is an "Airbnb for EV chargers" for India. People who own a home or society charger list it, and EV drivers nearby book a slot, pay in the app, scan the charger's QR code and charge.

```
ChargeShare/
├── backend/   FastAPI server: login, chargers, bookings, payments, payouts, admin API
├── mobile/    The Android + iPhone app (React Native / Expo)
├── admin/     Web admin panel (React + Vite): approve hosts and chargers, refunds, payouts
├── demo/      Clickable HTML prototype of the whole app (open chargeshare-demo.html in a browser)
├── docs/      Store listing text, launch checklist
└── render.yaml  One-click deploy of the server + admin panel on Render
```

**What works today, in test mode (no accounts needed):** OTP login (the code prints in the terminal), host verification, adding chargers with photos and map location, admin approval, map search, slot booking, test payment, host accept/decline, QR check-in, per-hour and per-kWh billing with automatic refunds, cancellation rules, ratings, problem reports, push notifications, weekly payouts, account deletion.

**Features that fix common complaints about other charging apps:**

| Problem with other apps | What ChargeShare does | Where in the code |
| --- | --- | --- |
| Broken chargers and slow refunds | "Charger not working" button gives an instant full refund; reliability % on every charger; 2 reports in a week take it offline automatically; hosts can mark "temporarily unavailable" | `booking_logic.report_not_working`, `serializers.charger_stats` |
| Too many apps and wallets | No wallet: pay each booking by UPI; printable receipt per session | `routers/receipts.py` |
| Overstaying, rigid slots | Extend a slot (pay only for the extra time); optional overstay fee after a 15-min grace period; unpaid dues pause new bookings | `request_extension`, `complete(..., by=)`, `ExtraCharge` |
| Exact home shown on a public map | Approximate pin and area only, until the host confirms | `serializers.fuzz` |
| No time-of-day pricing | Off-peak rate for a time window, priced in 15-minute steps | `booking_logic.window_price` |
| Housing-society disputes | Society mode: residents-only chargers, join codes, manager approvals, monthly per-flat usage statement | `routers/communities.py` |
| Busy chargers | Waitlist push when a slot opens; "Available now" filter | `notify_waitlist`, `search(available_now=)` |
| No evidence in disputes | Safety checklist at check-in, saved with a timestamp | `booking_logic.check_in` |

> Upgrading from an earlier copy? Delete `backend/chargeshare.db` and run `python -m app.seed` again. New tables and columns are created on start, but SQLite can't add columns to existing tables.

**Real-money mode** needs the accounts in Part B. Switching over only means filling in keys. No code changes.

---

## Part A: Run everything on your Mac (about 30 minutes)

### A1. Install the tools (once)

1. **Python 3.12**: download from https://www.python.org/downloads/macos/ and install. (The Mac's built-in Python is too old.)
2. **Node.js 22 LTS**: download from https://nodejs.org and install.
3. On your **phone**, install **Expo Go** from the Play Store / App Store.

Check in Terminal:
```bash
python3 --version   # 3.10 or newer
node --version      # v20 or newer
```

### A2. Start the server

```bash
cd ~/ChargeShare/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `backend/.env` and set `PUBLIC_BASE_URL` to your Mac's Wi-Fi address, for example `http://192.168.1.20:8000`.
To find your Mac's IP address, run `ipconfig getifaddr en0`.

```bash
pytest -q                       # runs the automated tests (all should pass)
python -m app.seed              # adds demo users + 5 demo chargers in Hyderabad
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000/docs to see every API endpoint. Leave this terminal running.
**OTP codes print in this terminal** (look for `*** OTP for +91… ***`).

Demo logins (created by the seed step):
| Who | Phone |
| --- | --- |
| Admin | 9000000001 |
| Host with 5 chargers | 9000000002 |
| Driver (also a resident of the demo society, join code LAKE01) | 9000000003 |

### A3. Start the mobile app

New Terminal tab:
```bash
cd ~/ChargeShare/mobile
cp .env.example .env            # then set EXPO_PUBLIC_API_URL=http://<your-mac-ip>:8000
npm install
npm run deps                    # installs the exact library versions that match this Expo SDK
npx expo start
```
Scan the QR code with your phone's camera (iPhone) or Expo Go (Android). Phone and Mac must be on the same Wi-Fi.

> The demo chargers are in Hyderabad. If you're elsewhere, tap "Search this area" after moving the map there, or add your own charger as a host.

### A4. Start the admin panel

New Terminal tab:
```bash
cd ~/ChargeShare/admin
cp .env.example .env
npm install
npm run dev
```
Open http://localhost:5173 and log in with `9000000001` (OTP in the server terminal).

### A5. Try the whole flow
1. Phone: log in as a new number, then go to **Host** tab, select **Become a host**, upload any photo as ID, and enter a UPI ID like `test@okaxis`.
2. Add a charger (photos, location, price).
3. Admin panel → **Hosts** → Approve; **Chargers** → Approve.
4. Log in on another phone (or log out) as the driver `9000000003`, find the charger, book, then tap **Pay (test)**.
5. As host: accept the request. As driver: **I've arrived: scan QR** (host's QR is under Host → your charger), then **Finish charging**.
6. Admin → **Payouts** → **Create this week's payouts**.

---

## Part B: Accounts you need to create (only you can do these)

| # | Account | Cost | What for | Time |
|---|---|---|---|---|
| 1 | **GitHub** (you have it) | Free | Store the code, deploy from it | done |
| 2 | **Supabase** (supabase.com) | Free tier | Database + photo storage | 10 min |
| 3 | **Render** (render.com) | ~US$7/month for the API | Runs the server and admin panel | 10 min |
| 4 | **Expo** (expo.dev) | Free tier | Builds the Android/iPhone apps in the cloud, push notifications | 5 min |
| 5 | **Google Cloud** (console.cloud.google.com) | Free at MVP scale (card needed) | Maps on Android | 15 min |
| 6 | **MSG91** (msg91.com) | ~₹0.2 per SMS | OTP SMS. In India this needs DLT registration of your sender ID and template (takes a few days) | 1–5 days |
| 7 | **Razorpay** (razorpay.com) | ~2% per payment, no setup fee | UPI/card payments, refunds. Needs business KYC (PAN, bank account, business proof) | 1–7 days |
| 8 | **Google Play Console** | US$25 once | Publish on Android | 1–2 days verification |
| 9 | **Apple Developer Program** | US$99 per year | Publish on iPhone | 1–2 days |

Tip: start #6, #7, #8 and #9 today. They involve verification waits.

---

## Part C: Put the server online

1. **Supabase**: New project → region **Mumbai (ap-south-1)**. Then:
   - Project Settings → Database → Connection string → **URI**: copy it (this is `DATABASE_URL`; replace `[YOUR-PASSWORD]`).
   - Storage → New bucket `public-media` (**Public** on), and bucket `private-docs` (**Public** off).
   - Project Settings → API: copy the **Project URL** (`SUPABASE_URL`) and the **service_role** key (`SUPABASE_SERVICE_KEY`; keep it secret).
2. **GitHub**: create an empty private repo named `ChargeShare`, then from `~/ChargeShare`:
   ```bash
   git init && git add . && git commit -m "ChargeShare MVP"
   git branch -M main
   git remote add origin https://github.com/<your-username>/ChargeShare.git
   git push -u origin main
   ```
3. **Render**: New → **Blueprint** → choose the repo. It reads `render.yaml` and asks for the values marked `sync: false`.
   Fill them in (Supabase values from step 1; `PUBLIC_BASE_URL` = the API's Render URL; `ADMIN_PHONES` = your number).
   Until MSG91/Razorpay are ready, temporarily set `OTP_PROVIDER=console` and `PAYMENT_PROVIDER=mock`. The OTP then appears in Render → Logs.
4. Open `https://<your-api>.onrender.com/health` and you should see `{"ok": true, ...}`.

---

## Part D: Switch on the real services

**SMS OTP (MSG91):** create an OTP template like `Your ChargeShare OTP is ##OTP##. Valid for 10 minutes.`, get it DLT-approved, then set on Render:
`OTP_PROVIDER=msg91`, `MSG91_AUTH_KEY`, `MSG91_TEMPLATE_ID`.

**Payments (Razorpay):** after KYC, Dashboard → Account & Settings → API Keys → generate **Live** keys.
Set `PAYMENT_PROVIDER=razorpay`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`.
Then Dashboard → Webhooks → Add: URL `https://<your-api>.onrender.com/payments/webhook`, events `payment.captured`; copy its secret to `RAZORPAY_WEBHOOK_SECRET`.
(Use Razorpay **Test** keys first; test UPI ID `success@razorpay` always succeeds.)

**Maps on Android:** Google Cloud → new project → enable **Maps SDK for Android** → Credentials → API key → restrict it to Android apps with your package name. Put it in `mobile/.env` as `GOOGLE_MAPS_ANDROID_KEY` (and in EAS env vars for cloud builds). iPhone uses Apple Maps, so no key is needed.

**Push notifications:** run `npx eas init` in `mobile/` (creates the Expo project and prints a project ID; put it in `EAS_PROJECT_ID`). Android push also needs a Firebase project: follow `npx eas credentials` → Android → "Google Service Account Key for Push Notifications (FCM V1)". iPhone push keys are created automatically during the first iOS build.

**Payouts to hosts:** every week, open Admin → Payouts → **Create this week's payouts**, send each amount by UPI from your business account, and click **Mark paid** with the UTR number. (Automatic payouts with Razorpay Route can be added later.)

**Store reviewers:** set `DEMO_PHONE` and `DEMO_OTP` on Render, and give these to Apple and Google in the review notes.

---

## Part E: Build and publish the apps

```bash
cd ~/ChargeShare/mobile
npm install -g eas-cli
eas login
eas init                       # once: links to your Expo account
```
Before the first build, in `mobile/.env` (or EAS → Project → Environment variables) set:
`APP_BUNDLE_ID` (e.g. `com.yourname.chargeshare`; **this can never change after the first release**), `EXPO_PUBLIC_API_URL` (your Render API URL), `GOOGLE_MAPS_ANDROID_KEY`, `EAS_PROJECT_ID`.
Also update the API URL inside `eas.json` (`preview` and `production`).

### Android (Google Play)
1. `eas build -p android --profile preview` gives an APK you can install on any Android phone to test.
2. `eas build -p android --profile production` creates an `.aab` for the Play Store.
3. Play Console → Create app → fill **Store listing** (text in `docs/STORE_LISTING.md`), **Data safety**, **Content rating**, **Privacy policy URL** = `https://<your-api>/legal/privacy`, **Account deletion URL** = `https://<your-api>/legal/delete-account`.
4. **Testing → Closed testing**: upload the `.aab`, add **at least 12 testers** (friends' Gmail addresses), and keep them opted in for **14 days**. Personal developer accounts must do this before going public.
5. Then **Apply for production** and roll out.

### iPhone (App Store)
1. `eas build -p ios --profile production`. EAS creates the certificates for you (log in with your Apple ID when asked).
2. `eas submit -p ios` uploads it to App Store Connect.
3. App Store Connect → your app → fill description, screenshots (6.7" and 6.5" iPhone), privacy "nutrition labels", privacy URL, review notes with the demo phone + OTP → **Submit for review** (usually 1–3 days).

**About payment rules:** because drivers pay for a real-world service (charging and parking), both Apple and Google let you use Razorpay instead of in-app purchase, so there's no 15–30% store commission.

---

## Part F: Running the business
- Daily: Admin → Hosts and Chargers (approve new ones), Reports (reply).
- Weekly: Admin → Payouts.
- Watch Render → Logs for errors. Back up: Supabase does daily backups on paid plans; on free, export weekly.
- Before launch: have a lawyer review `backend/legal/*.html` (fill in the `[PLACEHOLDERS]`), and check DISCOM rules in your launch city.

## How the money works
- Price is per hour (fixed for the slot) or per kWh (driver prepays the max; unused units refunded at finish).
- Platform keeps `COMMISSION_PERCENT` (default 10%), host gets the rest.
- Driver cancels ≥ 1 h before: full refund. < 1 h: 50% refund (host gets the other half minus fee). Host declines / doesn't answer / cancels: full refund. No-show: no refund.
- Unpaid bookings release the slot after 15 min. Unanswered requests expire at the start time. Sessions auto-complete 30 min after the slot ends.

## Where to change things
| What | File |
| --- | --- |
| Commission, cancellation window, booking limits | `backend/.env` (see `backend/app/config.py`) |
| Booking/payment/refund rules | `backend/app/services/booking_logic.py` |
| App colours | `mobile/src/theme.ts` |
| App screens | `mobile/app/` (one file per screen) |
| App name, icons, permissions text | `mobile/app.config.ts`, `mobile/assets/` |
