# Automatic WhatsApp tracking updates

After FDE confirms a new booking, OMS creates one tracking message for that order. Failed or uncertain FDE submissions do not create messages. Existing booked orders are not backfilled. The message explains that the parcel is registered and being prepared for handover, includes its tracking ID and https://www.fdedomestic.com, and does not claim it has been dispatched.

Start the usual `start_staff.command`, or start `start_whatsapp.command` separately. Link your business WhatsApp account in the dedicated Chrome window using your phone's Linked devices screen. Keep the computer awake, online and the browser signed in. Use your regular browser for chatting; leave this dedicated window to the worker.

The Orders app's WhatsApp page shows connection and message status. `queued` waits for the browser; `sent` means the new outgoing message displayed a WhatsApp sent check mark, not customer delivery/read confirmation. `blocked` means recipient/draft verification failed before Send: check the worker window, then use Retry. `needs_review` means a Send might have happened: check the actual chat and do not blindly resend. Messages over 24 hours old become `stale` for manual review. Invalid mobile numbers require a manual correction and update.

This uses WhatsApp Web UI automation, not the official WhatsApp Business API. Login expiry or interface changes can stop sending and require maintenance. For a supported server-side integration without an open browser, migrate the same outbox to the official Business Platform. Contact customers who agreed to receive order updates; honour requests to stop messages.

Implementation: a SQLite trigger captures future booking confirmations even from an already-running FDE worker. The hook and worker both insert idempotently by unique order ID. The worker verifies the visible contact phone and full draft, commits `sending` before clicking Send, and observes a new outgoing bubble with matching text and a sent check mark. Interrupted or ambiguous sends never retry automatically. A local process lock permits one worker.

The ignored `instance/whatsapp-browser-profile/` contains the linked session; protect it like a password and do not upload it. No login credentials or session files are committed. A setup test can be sent only to an explicitly authorized number with `whatsapp_worker.py --test-number NUMBER`; its persistent local marker prevents automatic repetition after a crash.

## Caller confirmation requests

Open **Confirm via WhatsApp** and enter the customer's name and mobile number. Submit queues the rack details and a request to reply YES. Pricing currently follows “more than 2”: 1–2 racks cost Rs.1,850 each; 3+ cost Rs.1,750 each. New requests send the saved product photo with the details as its caption. Previously queued/sent text-only requests retain their original content and are not resent. It does not create an order, courier booking, or label. Replies are checked in WhatsApp before the caller creates an order. Requests have their own message log; the tracking-message queue is unchanged. Duplicate form submissions reuse the request, and the same number cannot receive another request within 24 hours or while an earlier request is unresolved.
