# Courier callbacks

The owner/caller dashboard lists saved FDE rescheduled and rearranged parcels, with matching OMS names and tap-to-call numbers. Unmatched tracking numbers remain visible and require FDE contact details. The current station does not provide the courier's reason; rescheduled must not be labelled as customer no-answer.

The existing home station requests a report refresh five minutes after the previous refresh (or failed attempt). It must be running and signed into FDE. Bookings retain queue priority. This is polling, not instant tracking; timestamps and stale snapshot labels are shown.

A complete, fresh exception category queues one neutral WhatsApp follow-up per matching OMS order through the existing confirmation transport, without a photo. The current WhatsApp station login is required. Partial category samples do not trigger messages. A fresh observation is required again at claim and immediately before sending. Removal from the queue or a newer delivered/other status cancels pending messages. Status can still change at FDE between polls; the text invites already-delivered customers to tell us. A sent check mark does not establish delivery or a reply. Uncertain sends retain existing no-automatic-retry protection. No historic snapshot is messaged merely by deploying this feature.

Mark contacted records a staff timestamp; it does not change FDE or cancel the automatic message. Follow-up messages are also visible in the confirmation history. The one-message-per-order limit includes cancelled or uncertain attempts; staff can call instead.
