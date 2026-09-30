# Local storefront connection

The active Vue/Vite storefront is `/Users/dileepanayanajith/Documents/Acadamics/PRINTPRO3D STORE`, served on localhost:5173 (IPv6). Another unrelated app occupies IPv4 127.0.0.1:5173; use localhost for the storefront.

Checkout posts to its same-origin `/api/checkout` server middleware. It looks up authoritative item prices and stock in `src/data/products.json`, checks the displayed total, and sends authenticated intake to OMS `/api/website/orders`. No OMS token is included in the frontend bundle. Configuration is in the website's ignored `.env.local`; OMS reads its private `instance/website-token`. Keep both private. The previous website files are backed up in OMS `instance/website-backup-before-integration`.

Successful checkouts appear immediately in **Website orders & caller queue**, identified by WEB reference. Staff review availability, payment, courier city and actual parcel weight, then qualify the order into the existing print/scan/FDE flow. Bank payment is explicitly unverified; staff must verify payment and set the actual remaining COD before confirmation. No customer message or courier booking happens on website intake.

Checkout retries reuse an idempotency key. OMS saves intake and the receipt atomically. An unavailable OMS returns an error and leaves the cart intact; retry unchanged after service recovers. There is no background queue accepting orders while OMS is offline. Stock is checked against the catalog but is not reserved or decremented; staff confirm availability.

Run OMS normally, and run `npm run dev` in the storefront directory. Both servers must be running. `npm run preview` also includes this middleware, but deploying only the static `dist` directory does not. This is a local connection, not public hosting. For public launch, deploy a proper checkout backend with abuse controls, durable stock management and HTTPS before exposing it to customers.

Validation: 89 OMS tests; storefront TypeScript/production build; isolated end-to-end checkout using a temporary OMS database, duplicate retry, total tampering, stock limit and unavailable OMS. No test records or messages were created in the live OMS.

## Customer accounts, bank deposits and returns

Checkout email is optional. Username/password accounts also require no email. Passwords use PBKDF2-SHA256; customer sessions are separate from staff identities, stored hashed in OMS and carried by an HttpOnly SameSite cookie through the storefront server. Set `OMS_PUBLIC_HTTPS=1` in the storefront environment when deploying with HTTPS. Account orders are linked only at authenticated checkout; do not attach historical orders based on an unverified phone or email.

Bank orders now use COD zero and retain the actual order total separately. Staff must explicitly verify the bank payment in the lead review before qualifying the order. Success and account pages show the instruction to send the WEB reference and payment slip to WhatsApp 0721272082, with a prefilled chat button. The customer attaches the slip and sends it. This does not silently send a WhatsApp message; the restricted automated sender remains paused.

Customers can submit one return/help request per order; staff process these at `/customer-returns`. Approval changes the request status only, not courier bookings or refunds.

Account tracking shows OMS booking status, assigned waybill and the last authenticated FDE report snapshot with its sync timestamp. Staff refresh FDE data on the OMS dashboard. The public FDE page has `#track`; direct POST to its `track.php` returned Access denied during inspection. We do not treat that undocumented endpoint as a working API. An official FDE link is provided for the latest customer check.

## Activate Google login

Google Identity Services support is implemented but remains disabled until a real web client ID is configured. This does not require a client secret in the browser.

1. In Google Cloud, create/select a PRINTPRO3D project and configure Google Auth Platform branding and audience. The owner must review Google's terms and provide the support/contact email.
2. Create an OAuth client of type **Web application**. Set Authorized JavaScript origins to `http://localhost:5173` for local testing. Add the exact HTTPS storefront origin when deployed. This uses the GIS JavaScript callback, not an authorization-code redirect flow.
3. Add test users while the consent app is in testing, or complete Google's required publishing steps.
4. Set `OMS_GOOGLE_CLIENT_ID` for OMS, or save just the client ID to private `instance/google-client-id`. The client ID is public configuration, not a client secret. The API reads the file on each configuration/verification request.
5. Reload `/account` and test real sign-in. The backend validates signature, expiry, audience and issuer using Google's official `google-auth` library. Google subjects are independent identities and are not merged with username accounts by matching email.

No live Google sign-in has been verified until step 5 completes. Prefer Python 3.11+ for deployment; the current local Python 3.9 environment is legacy.

Official references:
- https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid
- https://developers.google.com/identity/gsi/web/guides/verify-google-id-token

Account password reset and linking old guest orders are not implemented. The account UI says so. Do not expose the old storefront demo admin login as real staff authentication; staff operations use the separately authenticated OMS.
