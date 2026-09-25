# PRINTPRO3D OMS

Caller enters details once → packing assigns an existing CCP sticker → a dedicated browser fills FDE → staff verify booking → official label → packed.

The app and browser-worker implementation are ready for a supervised local pilot. No real parcel has been submitted during development. Live receipt detection and automatic label download/printing are not commissioned.

## Technology

| Technology | Purpose |
|---|---|
| Python + Flask | Small web app and order validation |
| Jinja + HTML/CSS | Caller, courier queue and packing screens; no separate frontend build |
| SQLite | Persistent orders, waybill reservations and job states |
| Playwright + Chromium | Fill FDE's observed Existing CCP / CRE form in a separate browser |
| Private local PDF storage | Serve official waybills to packing |

An LLM is not needed for each booking: field values come directly from the confirmed order. Browser automation does the repetitive form work, with exact destination selection and value checks. No per-order AI subscription is required by this implementation.

## Start the app

Python 3.9+ on macOS/Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-browser.txt
PLAYWRIGHT_BROWSERS_PATH=instance/browser-binaries python -m playwright install chromium
python run.py
```

Open http://127.0.0.1:5055. The default pilot is loopback-only, with automatic submission off. App-only installs can use `requirements.txt`. Tests: `python -m unittest discover -s tests -v`.

## Start the FDE browser

In another terminal in the same repository, using the same environment:

```sh
python worker.py --login
```

Sign into FDE yourself in the dedicated Chromium window. Press Enter in the terminal after login to continue the worker in that SAME browser. Do not close/restart it after signing in: FDE uses a session that may not survive browser restarts.

You can also start `python worker.py` directly. If a queued order encounters the login page, it pauses as `login_required`; sign into that open worker window and preparation resumes automatically. No submit is attempted during this login recovery.

The worker opens a visible browser and polls the shared queue. It fills one order and keeps the form open for review; later orders wait. The FDE login in Codex's in-app browser is separate and is not copied. No portal password is requested by or stored in application code. The persistent Chromium profile contains session credentials, so restrict its access and keep it out of Git.

## Daily pilot flow

1. Qualify the lead in Meta as usual, then enter the shipment in OMS. Meta sync is deferred.
2. Complete recipient, phone, address, exact FDE destination city, product/variant, quantity, COD and packed grams. Qualify once to create an order.
3. Packing sees the order immediately. Scan/type the existing CCP sticker number and confirm the displayed FDE weight band in whole kg. Default rounds up; the operator must confirm it. CRE allocation has not been commissioned.
4. Queue form fill. The caller/courier screen shows offline, queued, preparing, prepared or needs-attention states.
5. Review the worker's FDE form. Default mode never clicks Submit. For this initial pilot, staff can submit in FDE, check the created record, and confirm the matching tracking number in OMS.
6. Use FDE Label Print, save the official label PDF and attach it to the order. Packing opens/prints that PDF and marks packed. Actual PDF retrieval/printing remains manual.

The worker pauses on login expiry, unknown waybill, populated parcel, missing/ambiguous city or changed controls. Raw portal errors, screenshots and customer data are not copied into routine logs.

## Optional supervised submit (off by default)

Only for a deliberately approved live pilot: start the web app with `OMS_ENABLE_LIVE_BOOKING=1` and the worker with `python worker.py --enable-submit`. After a form is prepared, an administrator reviews it and selects **Submit this booking once**. Both switches and a fresh online worker are required; this is not unattended mode.

The worker persists `submitting` before clicking. Whether the click returns or times out, the order moves to `needs_review` until staff verify the FDE record. This is intentional: success/duplicate responses have not been observed on a real booking yet. Restarted or uncertain work never retries automatically. Before retrying, staff must check FDE and explicitly confirm no booking exists. Never manually submit and approve automatic submission for the same order.

## Implemented safeguards and limits

- One order per qualified lead, one job per order, unique CCP waybill reservations, including prefix aliases.
- Integer cents/grams; whole-kg FDE band explicitly confirmed at queue time.
- Exact autocomplete selection; prepared values rechecked immediately before an approved click.
- Single worker process lock, durable job states, restart reconciliation and role separation.
- Packer can reserve a sticker/queue preparation and pack; only admin can approve submission, confirm booking or export.
- CSRF, escaped templates, parameterized SQL and role-level activity history.
- Qualified shipment details are frozen. Editing/cancelling a qualified order is not implemented; check data before qualification.
- One product/variant line per order. Use notes for production instructions.
- PDF validation checks file signature, not recipient/tracking correctness. Upload only official labels from FDE.

## Online deployment later

Start with one persistent macOS/Linux machine running both the app and a visible browser worker. It must stay on while processing orders. A production server will need a managed graphical session for the current headed worker; unattended headless operation is not commissioned.

For access from both sites, use HTTPS reverse proxy and a private access gateway with MFA/rate limiting. Configure stable `OMS_SECRET`, strong distinct `OMS_ADMIN_PASSWORD` and `OMS_PACKER_PASSWORD`, and `OMS_HTTPS=1`. Run Flask under `gunicorn --workers 1 --bind 127.0.0.1:5055 run:app`. Never expose the development server or use ephemeral storage. Role passwords are for a small pilot; add named users if individual audit is needed.

Back up SQLite with its backup API, or stop both app and worker before copying database/PDF files. Encrypt backups and test restore. Do not routinely copy the authenticated browser profile into backups; re-login after restore. Agree customer-data retention before live use.

## Files

- `oms/__init__.py`: web routes, order workflow and initial schema.
- `oms/automation.py`: additive migration, reservations, queue states and reconciliation.
- `oms/fde_browser.py`: observed CCP selectors and form checks.
- `worker.py`: dedicated browser lifecycle and queue polling.
- `oms/templates/`: caller, courier and packing screens.
- `tests/`: workflow and automation failure-mode tests (mocked browser, not proof of live FDE submission).
- `docs/FDE-INTEGRATION.md`: inspection evidence and remaining commissioning work.
- `instance/`: private runtime data/profile/browser binaries, ignored by Git.

A local Git repository has been created. No remote GitHub repository or hosted service has been provisioned.
