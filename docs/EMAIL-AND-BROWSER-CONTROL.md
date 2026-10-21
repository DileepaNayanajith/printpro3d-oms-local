# Customer emails and browser controls

## Email setup (disabled until configured)
Use a business mailbox you own, for example orders@your-domain.lk. Configure the mail provider's STARTTLS SMTP credentials as private Railway variables:

- OMS_SMTP_HOST
- OMS_SMTP_PORT (587 by default; STARTTLS required, not implicit SSL 465)
- OMS_SMTP_USER
- OMS_SMTP_PASSWORD (provider app password / SMTP credential, not in Git)
- OMS_EMAIL_FROM (the verified sender email address only)

Configure the provider's SPF/DKIM records for your domain before sending to customers. This repository does not provision a mailbox or DNS.

New website orders may supply optional `email`, or the existing checkout `Email: address` line in notes. No email means no email updates. Existing explicit email notes are retained for future status changes, without sending historical updates. Status events are received, confirmed, booked, packed and dispatched. Saved status is the source of truth; booked does not claim dispatch. Each order/status is queued once. The SMTP worker runs in the cloud process. Unconfigured or older-than-24-hour messages are not sent. SMTP acceptance is not proof of inbox delivery. Ambiguous send failures require review, never automatic resend. See `/email-updates` as owner.

## Mac buttons
The browser controller is a small paired agent. It accepts only FDE or WhatsApp worker launch requests, never arbitrary shell commands. Owner-only buttons are on `/station`, require CSRF and an online controller. Requests expire after five minutes and are consumed once. Existing OS worker locks prevent duplicate browser workers.

From the paired Mac station folder run `.venv/bin/python install_mac_controller.py` once. It installs `~/Library/LaunchAgents/lk.printpro3d.station-controller.plist`, starts at login, and writes logs only under the existing station folder. It does not open browsers until requested. Manual alternative: `start_mac_controller.command`.

To uninstall: `launchctl bootout gui/$(id -u)/lk.printpro3d.station-controller`, then remove that plist. This does not remove orders, logins or the station pairing.

The Mac must be on, logged in and connected to the internet. Browser login expiry/QR sign-in still requires the person at the computer. This does not promise automatic credential login. The Windows source package includes `windows/Start Controller.cmd`; run after pairing (a separate Windows startup shortcut can be configured on that PC).

Mac's existing `confirmation_only` and `confirmation_after` preferences are preserved. The launcher does not remove old-message exclusions or enable bulk historic dispatch sending.
