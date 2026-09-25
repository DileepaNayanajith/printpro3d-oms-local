# FDE findings — 25 September 2026

## Authenticated inspection

The user signed into FDE and authorized read-only inspection. No booking, upload, print job, account change or customer-data submission was made.

| Path | Verified observation | Decision |
|---|---|---|
| API → New Parcel | “Sorry! You are not eligible to this feature.” | Unavailable to this account now; request enablement from FDE. |
| API → Existing Waybill | Same eligibility message. | Do not bypass the restriction or guess API endpoints. |
| Existing CCP / CRE Parcel | Requires Waybill ID and a Go button. Instructions say enter only digits for CCP stickers. | Existing sticker number is an input, not necessarily an automatically generated output. No number entered during inspection. |
| New Parcel | Accessible form with weight, description, order ID, amount, exchange, recipient name, two contacts, address and city. | Candidate alternative; success, tracking allocation and label availability untested because no live submission was made. |
| Waybill Upload | CSV picker, Upload button, official template; states “allows only CRE & CCP waybills”. | Strongest current candidate for existing sticker workflow. Import semantics still require a controlled trial. |
| Waybill Download | Generate Date filter and Search button. | Page exists; download contents were not tested. |
| Label Print | Date, From/To time, status filter, Print and 10x10 Print buttons. | Batch label UI confirmed. Actual output, units/layout and PDF export remain untested. |

### Official CSV template

Downloaded the blank template linked by the authenticated upload page. Preserved unchanged in `docs/fde-waybill-upload-template.csv`:

```text
Waybill ID,Order ID,Parcel Type,Parcel Description,Recipient Name,Recipient Mobile,Recipient Mobile,Recipient Address,Recipient City,COD Amount,Exchange (0 or 1)
```

Both contact columns have the identical header `Recipient Mobile`; mapping must be positional. There is no weight column in this template. Accepted Parcel Type values, full-prefix vs digits-only Waybill ID format for CSV, city validation, encoding, blank second-phone handling, charges/weight defaults, duplicate behavior and partial-failure results are not documented in the downloaded file. Do not infer CSV rules from the single-parcel form's CCP digit-only instruction.

### Recommendation for PRINTPRO3D

Caller continues qualifying in Meta Business Suite, then types shipment details into OMS for now; Meta syncing is deferred. For the existing CCP workflow, packing scans or enters the assigned physical sticker number once, OMS reserves that exact number for that order, and a single browser worker uploads an OMS-generated FDE CSV. Initially use one-row batches to verify behavior; use larger batches only after per-row reconciliation is reliable. Generate CSV deterministically, not through an AI model deciding field values on every run.

The worker must confirm imported records and match order reference/waybill before declaring success, then use FDE's official label UI. Automating the portal upload still removes retyping. A scanner or a verified preloaded inventory of unused waybill numbers is needed to remove manual waybill entry. Never invent/guess numbers or allocate the same sticker twice.

If FDE confirms New Parcel creates usable digital waybills for this account, that route could eliminate the physical-sticker inventory step. Opening the form alone does not establish this. API enablement remains the preferable longer-term integration.

### Next validation inputs

Confirm whether packing uses preprinted CCP/CRE stickers and whether the user wants to retain them. Obtain an unused assigned waybill for a user-authorized controlled booking, or a FDE sandbox, before testing write behavior. Confirm the CSV fields above and verify a real official label against the actual printer. No permission for a real booking is implied by portal-inspection authorization.

Sources inspected:
- https://www.fdedomestic.com/client/new_api_doc.php
- https://www.fdedomestic.com/client/existing_waybill_api_doc.php
- https://www.fdedomestic.com/client/ccp_parcel_add.php
- https://www.fdedomestic.com/client/new_parcel_add.php
- https://www.fdedomestic.com/client/waybill_upload.php
- https://www.fdedomestic.com/admin/assets/images/default/waybill_upload_template.csv
- https://www.fdedomestic.com/client/waybill_download.php
- https://www.fdedomestic.com/client/label_print.php

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
