# FDE findings — 25 September 2026

| Path | Evidence | Conclusion |
|---|---|---|
| API | Official Shopify-app privacy policy mentions Parcel Add API, client ID and API key. | Prefer API, subject to merchant access and verified contract. |
| API contract | No verified public endpoint/auth/response specification obtained. | Do not guess endpoints from policy fields. |
| Portal | Requested booking page redirected to `client/signIn.php#you_must_login_first` in browser. | Booking form, label controls and import menus remain uninspected without login. |
| CSV/Excel | Targeted official-site searches found no public import specification. | Unconfirmed, not absent. |
| Browser fallback | Sign-in page verified; booking controls not accessible. | Design only until authenticated inspection. |

Primary sources:
- https://www.fdedomestic.com/fardar_express_app_privacy_policy.php
- https://www.fdedomestic.com/client/ccp_parcel_add.php
- https://www.fdedomestic.com/

The policy lists recipient details, parcel weight/description, COD, order reference and waybill identifier. It does not establish units, endpoint contracts or tracking allocation. In particular, PRINTPRO3D may use preallocated tracking numbers; do not assume booking allocates them.

## Obtain from FDE

Merchant API access, current documentation and sandbox examples; authentication, city IDs, weight units, COD/delivery-charge semantics, tracking allocation or preallocated ranges, lookup by reference, idempotency, PDF/barcode format, rate limits, cancellation and status lookup/webhooks. If API access is unavailable, ask for the bulk import template and per-row result export, then whether portal automation is supported.

No contact message, credentials, customer data or booking was submitted during investigation.

## Safe integration sequence

1. Qualifying saves an immutable order plus unique job atomically. Keep `PP3D-000001` reference stable across attempts.
2. One worker claims a job transactionally and commits `submitting` before the external request; never hold a DB lock across network calls.
3. Reconcile by reference before retrying. Use idempotency keys only if supported. A timeout after submit or restart during submit goes to `needs_review`; never blindly rebook. Unknown lookup results do not prove absence.
4. Store validated unique tracking and official PDF on success. If only label retrieval fails, retry label retrieval, not booking.
5. Explicit validation failures go to operator review; safe reads may retry with bounded backoff. Add worker lease, attempt and error columns in a schema migration before implementing the worker.
6. Browser fallback: dedicated protected session outside Git; staff handle login, OTP/CAPTCHA. Use inspected labelled controls, validate destination choices, review during commissioning and submit once. Login redirect, layout change or missing receipt pauses the job. No guessed selectors or bypassing access controls.
7. Match success receipt/parcel record to reference and recipient, capture tracking and download official waybill. Restrict/redact logs and screenshots.
8. Bulk fallback: map the verified template and reconcile each result row before retrying failures. Internal OMS CSV is not an FDE upload template.

## Printing

Current MVP: official PDF plus operator print dialog. Next: automatic official PDF retrieval and a print-job table; a small packing-site agent polls approved jobs and prints to configured A4/thermal printer. Record acknowledgement, printer, attempt and reprint reason. Uncertain printer acknowledgement needs review rather than duplicate automatic labels. Confirm paper size/scaling/barcode scan with FDE.

## Commissioning checks

Sandbox booking; preallocated/generated tracking; double-click; timeout after FDE acceptance; restart during submit; expired login; invalid city; label failure after booking; duplicate tracking; packing role permissions; scanned printed labels. Enable live automation only after a controlled reconciled pilot.
