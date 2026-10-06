# Online OMS + home Windows station

Status: implementation and automated tests are ready. Cloud deployment, final data
cutover, Windows setup and physical HP print verification have **not** been performed.
The current Mac installation remains the live system until commissioning finishes.

## What runs where

- Cloud: Flask/Waitress, one SQLite database on a persistent volume, staff logins,
  orders, dashboard, packing and durable job queues. One replica only.
- Owner's Mac/phone: browser login; no printer, courier or WhatsApp worker needed.
- Home Windows PC: outbound HTTPS polling, HP printing via SumatraPDF, dedicated
  FDE and WhatsApp browser profiles. No inbound router ports or shared database.
- Staff: Print selected, attach CCP stickers, scan order then CCP barcode, pack.
  The scan authorizes one courier submission. A successful booking queues the message.
- PC offline: orders still save online; jobs wait. The station must be awake, logged
  into Windows, running and online to process them. Browser sessions may need re-login.

## Hosting proposal (verify before purchase)

Railway Hobby with one web service and a volume mounted at `/data`. Minimum $5/month
includes $5 usage; charges can exceed $5. Configure an owner-approved spending limit.
Use the included HTTPS domain initially. Do not enable serverless sleeping or multiple
replicas. The SQLite database must never live on an ephemeral application filesystem.

Sources checked 28 September 2026:
- https://docs.railway.com/pricing
- https://docs.railway.com/volumes
- https://docs.railway.com/backups
- https://www.sumatrapdfreader.org/docs/Command-line-arguments

## Deploy a staging service first

1. Owner signs into Railway, approves the selected billing plan, and connects the
   private `DileepaNayanajith/printpro3d-oms-local` repository and its configured Railway deployment branch
   branch. Do not upload local browser profiles, `.env`, logs, or staff-access files.
2. Build with the included Dockerfile. Create a persistent volume mounted at `/data`.
   Keep exactly one replica and disable automatic sleeping.
3. Set private Railway variables (do not paste values in chat):
   - `OMS_SECRET`: newly generated 32+ character random secret.
   - `OMS_OWNER_PASSWORD`: new 16+ character owner password for first startup.
   - `OMS_PACKING_PASSWORD`: new 16+ character packing01 password for first startup.
   - `OMS_SENDER_NAME`, `OMS_SENDER_ADDRESS`, `OMS_SENDER_PHONE`: label sender details.
   - Docker already sets `OMS_CLOUD=1`, `OMS_HTTPS=1`, `OMS_INSTANCE_PATH=/data`.
   - Railway supplies `PORT`.
4. Deploy, generate the HTTPS domain, check `/healthz`, and sign in as owner.
   Set volume backup schedules and verify an actual restore into a separate service.
   Remove initial password variables after named accounts are created; never reset
   the session secret accidentally during a deploy.
5. Owner > Home PC > Create pairing key. This secret is shown once and stored hashed
   on the server. Enter it only in Windows setup. It can be revoked from Home PC.
6. Commission using test orders and an explicitly authorized personal WhatsApp number.
   Do not book a fake/test shipment with FDE. Validate a real ready parcel only when
   the owner explicitly identifies it for the live courier check.

## Install on the home Windows PC

Requirements: Windows 10/11 64-bit, Python 3.11 64-bit with launcher, HP printer driver,
SumatraPDF from https://www.sumatrapdfreader.org/free-pdf-reader. These downloads may
require the Windows user's approval. No unsigned binaries are bundled here.

1. Extract `PRINTPRO3D-Windows-Station.zip` to a permanent folder.
2. Double-click `windows/Setup.cmd`. It installs Python dependencies and the browser,
   protects the local station data folder for this Windows user, then asks for the
   HTTPS OMS address, pairing key, SumatraPDF path and exact HP printer name.
3. In HP printer preferences select **A4, Landscape, one page per sheet, single-sided**.
   Sumatra's landscape switch rotates content; printer paper orientation must also
   be configured. Print and check one paired test sheet (two A5 labels on landscape A4).
4. Double-click `windows/Start Station.cmd`. Keep all three windows open.
   Sign into FDE in its browser; link WhatsApp in its separate browser.
5. Open the online OMS in the normal browser and log in as packing01. Confirm printing,
   scanner entry and packing updates. Owner checks the same changes from the Mac.
6. Optional: after commissioning, place a shortcut to Start Station.cmd in the Windows
   user's Startup folder. Do not run browser workers as a background Windows service;
   they need the logged-in interactive desktop.

Local secrets and browser sessions live in `%LOCALAPPDATA%\PRINTPRO3D-station`, outside
this package. Never share that folder. Updating the package preserves the pairing and
logins. Replacing a pairing key requires rerunning Setup on the PC.

## Final data cutover (single writer)

Do not copy a live SQLite file with its WAL omitted. Do not run two independent order
systems after the switch: duplicate order references and messages could result.

1. Schedule a short pause. Stop order entry and all Mac workers; reconcile any uncertain
   courier/WhatsApp/print jobs first. Keep the Mac database as a rollback backup.
2. Export with SQLite's snapshot API:
   `python cloud_transfer.py export instance /private/path/printpro3d-migration.zip`
   The archive contains customer data and password hashes. It excludes browser
   sessions, pairing keys, session secrets, logs and staff passwords in plaintext.
3. Stop the staging cloud service. Preserve its test data separately, then provision
   the production volume **without an existing oms.sqlite3**. Securely transfer the
   migration archive into that environment and run:
   `python cloud_transfer.py restore /private/path/printpro3d-migration.zip /data`
   The restore refuses to overwrite an existing database or accept arbitrary zip paths.
4. Start cloud, compare order count, newest reference, COD total, rack corrections,
   tracking numbers, sent WhatsApp records and staff logins against the snapshot.
   Historical `sent` messages stay sent. Interrupted/pending prints and messages are
   held for review; do not bulk resend them. No previous booking is automatically retried.
5. Pair Windows with the production URL. Test one label and one authorized real order.
   Confirm automatic booking, exactly one WhatsApp send, and packing visibility.
6. Only then direct everyone to the cloud URL. Leave old Mac workers disabled. Archive
   the old installation read-only. Delete temporary transfer archives after verified
   backups and cutover. If rolling back after new cloud orders exist, migrate those
   changes back first; never restart a stale Mac database.

## Failure handling

- A cloud claim is committed before the worker receives a job.
- The PC prepares and verifies the form/draft/PDF, then requests permission to start.
- The cloud commits `executing` before any external submit/send/print.
- The PC stores the result locally before reporting it. Lost acknowledgements retry
  the result only, never the external action.
- Expired or uncertain tasks require review. They are never silently requeued.
- FDE report refreshes are read-only, with timestamps and partial-coverage notes.
- Windows/browser/printer-specific behavior still needs physical commissioning.
