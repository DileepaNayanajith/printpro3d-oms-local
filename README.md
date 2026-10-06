# PRINTPRO3D Order Management

An order management system for PRINTPRO3D’s day-to-day sales, packing and courier work. It connects online order entry with the computer used for parcel labels, barcode scanning and FDE Domestic bookings.

## Order workflow

1. Staff enter a confirmed order, or receive one through the connected storefront.
2. Select orders and print parcel labels, two per landscape A4 sheet.
3. Scan the order barcode and the courier sticker to queue an FDE booking.
4. The connected station checks the details and submits the booking through its signed-in FDE browser.
5. Packing staff scan parcels OUT when handing them over. Courier reports support delivery follow-up and the business overview.

The cloud app holds orders and job status. The station computer handles the physical printer and browser sessions; it must be running for those jobs to proceed.

## Features

- Staff accounts with separate owner, caller and packing access.
- Batch waybill printing and barcode-based courier booking.
- Restricted packing handover screen with parcel counts.
- Courier status snapshots and customer callback queues.
- Website visitor and order overview.
- Hot Wheels rack selection, colour and quantity pricing.
- Physical return scanning, dated expenses and estimated profit reporting.
- Customer notification queues and prepared WhatsApp updates.

Profit figures depend on recorded expenses and available courier observations. They are estimates, not a courier settlement statement. Browser login expiry or portal changes can pause jobs for review.

## Technology

| Component | Technology |
| --- | --- |
| Application | Python, Flask and Jinja templates |
| Data | SQLite on persistent storage |
| Courier integration | Playwright with a dedicated Chromium session |
| Parcel labels | ReportLab PDFs |
| Online hosting | Railway |
| Station | Windows worker; paired macOS FDE launcher |

Courier form values come from saved orders. Booking does not require an AI model or a per-order AI service.

## Development

Use Python 3.11, matching the cloud runtime.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-browser.txt
PLAYWRIGHT_BROWSERS_PATH=instance/browser-binaries python -m playwright install chromium
python run.py
```

The local app opens at `http://127.0.0.1:5055`. Local development and a paired cloud station use different queues. Do not start a local worker expecting it to process cloud orders.

Run the automated checks with:

```sh
python -m unittest discover -s tests
```

Tests cover application behaviour and simulated integration failures. They do not verify physical printing or a live courier booking.

## Operations guides

- [Cloud deployment and Windows station](docs/CLOUD-AND-WINDOWS.md)
- [Staff workflow](docs/STAFF-GUIDE.md)
- [Profit, pricing and returns](docs/PROFIT-AND-RETURNS.md)
- [Dispatch notifications](docs/DISPATCH-MESSAGES.md)
- [WhatsApp setup and recovery](docs/WHATSAPP.md)
- [FDE integration notes](docs/FDE-INTEGRATION.md)

On the configured Mac, `start_mac_cloud_fde.command` starts the paired FDE worker. Sign in through the browser it opens and keep that browser and Terminal running. This launcher does not start a printer worker.

## Repository layout

```text
oms/              Application, integrations, templates and assets
home_worker.py    Cloud-connected station worker
cloud_serve.py    Cloud application entry point
windows/          Windows setup and launch scripts
station-updates/  Targeted station updates
tests/           Automated checks
docs/            Setup and operating guides
```

## Private runtime data

Keep credentials, station pairing keys, customer records, PDFs and browser profiles out of Git. Runtime files belong in the ignored `instance/` directory. Back up the persistent database and required parcel files separately. An uncertain booking or print result should be checked before retrying to avoid duplicates.

## Development note

Developed for PRINTPRO3D with AI-assisted coding and documentation. Product requirements and operating decisions are driven by PRINTPRO3D’s workflow.
