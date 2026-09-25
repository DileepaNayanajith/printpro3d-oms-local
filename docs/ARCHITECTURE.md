# Small MVP architecture

Facebook → caller queue → qualified order + booking job → FDE adapter → tracking + official PDF → packing queue → packed.

One Flask application, server-rendered pages, one SQLite database, private PDF storage. No SPA, Redis, microservices or separate packing backend. Add one background worker only after verifying FDE's contract. Use PostgreSQL later if multiple app instances/write contention justify it.

## Data and states

Leads hold recipient/product/quantity/notes, money in integer cents and weight in grams. Qualification freezes shipment details. Unique orders.lead_id prevents duplicate conversion; one booking job per order and a stable merchant reference provide local deduplication. Unique tracking prevents attaching one shipment to different orders.

Current lead states: new, callback, rejected, qualified. Orders: awaiting_booking, booked, packed. Jobs: pending, succeeded (manual reconciliation). Future worker migration: submitting, needs_review, failed, lease metadata and receipt/error fields. The current job table and adapter interface are a foundation; neither performs automation.

Caller/admin can qualify, export and reconcile. Packing sees packing information and official waybills, and can mark packed. Files are served through protected routes, not public static paths. Role-level activity history records conversion, booking, waybill attachment and packing. Named user identities are a future upgrade.

## Delivery stages

1. Implemented: manual lead intake, call qualification, internal order CSV, manual FDE bridge, official PDF attachment, packing queue.
2. FDE integration: obtain account contract, implement provider adapter, single worker, reconciliation and sandbox tests.
3. Reduce typing: import approved Facebook CSV with external lead-ID deduplication; optional verified Meta webhook later. A lead is never automatically qualified.
4. Packing efficiency: automatic label retrieval, print agent, dispatch manifest; later delivery status/returns/COD reconciliation.

A single product/variant line keeps the starter small. Qualified-order edit/cancel flows and dispatch state are intentionally deferred, and must reconcile any courier booking when introduced. Online pilot needs HTTPS gateway, strong configured credentials, persistent disk, backup/restore testing and monitoring. No production hosting or external repository has been provisioned.
