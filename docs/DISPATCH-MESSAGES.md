# Dispatch WhatsApp timing

Tracking notifications now queue only when packing records a parcel OUT (`orders.status=dispatched`). Booking alone does not queue or authorize sending. Existing unsent booking messages wait in `awaiting_handover`; scanning OUT refreshes their text and timestamp. Sent/uncertain messages are never automatically resent. Historical dispatched orders are not backfilled by migration. An already-executing pre-upgrade send cannot be recalled.

The dispatch body says the parcel was handed to FDE and includes the order reference, tracking number and FDE website. The home WhatsApp station must be online and signed in. A send is queued immediately, not guaranteed delivered immediately. Sending still uses the existing WhatsApp Web transport; this timing change does not prevent account restrictions. No paid provider is activated.

The legacy booking event table is retained for compatibility but is now populated by an order dispatch trigger. The cloud queue also checks dispatch at claim and before arming a send. Duplicate handover scans and previously sent tracking notifications remain idempotent. Courier exception follow-ups remain a separate notification flow.
