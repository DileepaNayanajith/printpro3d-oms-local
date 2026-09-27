# Automatic WhatsApp tracking updates

After FDE confirms a new booking, OMS creates one tracking message for that order. Failed or uncertain FDE submissions do not create messages. Existing booked orders are not backfilled. The message explains that the parcel is registered and being prepared for handover, includes its tracking ID and https://www.fdedomestic.com, and does not claim it has been dispatched.

Start the usual `start_staff.command`, or start `start_whatsapp.command` separately. Link your business WhatsApp account in the dedicated Chrome window using your phone's Linked devices screen. Keep the computer awake, online and the browser signed in. Use your regular browser for chatting; leave this dedicated window to the worker.

The Orders app's WhatsApp page shows connection and message status. `queued` waits for the browser; `sent` means the new outgoing message displayed a WhatsApp sent check mark, not customer delivery/read confirmation. `blocked` means recipient/draft verification failed before Send: check the worker window, then use Retry. `needs_review` means a Send might have happened: check the actual chat and do not blindly resend. Messages over 24 hours old become `stale` for manual review. Invalid mobile numbers require a manual correction and update.

This uses WhatsApp Web UI automation, not the official WhatsApp Business API. Login expiry or interface changes can stop sending and require maintenance. For a supported server-side integration without an open browser, migrate the same outbox to the official Business Platform. Contact customers who agreed to receive order updates; honour requests to stop messages.

Implementation: a SQLite trigger captures future booking confirmations even from an already-running FDE worker. The hook and worker both insert idempotently by unique order ID. The worker verifies the visible contact phone and full draft, commits `sending` before clicking Send, and observes a new outgoing bubble with matching text and a sent check mark. Interrupted or ambiguous sends never retry automatically. A local process lock permits one worker.

The ignored `instance/whatsapp-browser-profile/` contains the linked session; protect it like a password and do not upload it. No login credentials or session files are committed. A setup test can be sent only to an explicitly authorized number with `whatsapp_worker.py --test-number NUMBER`; its persistent local marker prevents automatic repetition after a crash.
