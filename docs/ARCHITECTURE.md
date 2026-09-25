# PRINTPRO3D pilot architecture

Meta qualification stays manual. Caller types shipment into OMS once; qualified order appears at packing immediately. Packing reserves an existing CCP number; one browser worker fills the FDE form; operator confirms the courier result; packing receives the official label.

## Small stack

Flask/Jinja serves all screens. SQLite stores leads, orders, jobs and audit events. Playwright controls one dedicated visible Chromium profile. PDFs are private files served by authenticated routes. No Redis, React, message-broker service or per-order LLM calls. Move to PostgreSQL only when multiple application instances or write contention justify it.

Caller and packer connect to the same app; browser worker must share its local database and stay running. The current worker is macOS/Linux only (OS process lock). Online deployment requires persistent storage, HTTPS/access gateway and a graphical browser session. The in-app browser's login is not reused or extracted.

## Job states

`pending` (awaiting CCP number) → `queued` → `preparing` → `prepared`.

Default: staff review/submit in FDE and verify the parcel, then OMS records `succeeded` and order `booked`.

Optional supervised submit: `prepared` → admin approval → `approved` → durable `submitting` → `needs_review` → manual parcel verification → `succeeded`.

Preparation failures become `blocked`. Interrupted preparation/review/submission becomes `needs_review`, since staff might have interacted with the visible form. Only explicit operator reconciliation can requeue blocked/uncertain jobs. A worker lock prevents concurrent browser processes. Queue claim and submission-state writes are transactional and never keep the DB lock over a browser operation.

Prepared status means the form was filled/checked; it does not mean a parcel exists. A return from the Submit click is also not proof of success. Receipt recognition is deliberately deferred until a real controlled booking shows FDE's response and reconciliation behavior.

## Data integrity

One order per lead and one job per order. Unique waybill reservations normalize optional CCP prefix while preserving leading zeros. Legacy manually confirmed tracking is checked for prefix aliases. A reservation cannot confirm a different tracking number. Existing records survive an additive migration.

The worker uses the observed CCP page, numeric waybill lookup, verified parcel heading, field IDs and exact city autocomplete option. It never invents a destination ID. Live inspection showed the hidden city field can remain blank after selection; preserve it and compare its observed value before submit. Weight bands are explicit operator-confirmed whole kg. Qualified data is frozen for the pilot.

## Next commissioning work

- Run real auto-fill with a staff-controlled dedicated login and one confirmed order.
- Verify exact destination, weight, COD and recipient, then make one authorized booking.
- Capture observed success/duplicate behavior and implement record reconciliation before automatic booking confirmation.
- Validate official label extraction (including 10x10 option) and actual printer output.
- Add auto-print agent only after printer acknowledgement/reprint handling is defined.

CSV is not the selected integration path. The blank CSV template remains as reference only. FDE API access is currently denied for the inspected account.
