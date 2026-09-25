# PRINTPRO3D OMS

Lightweight Facebook lead → caller qualification → order → FDE → packing starter. A local Git repository, not yet hosted or connected to FDE.

## Run

Python 3.9+:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open http://127.0.0.1:5055. Unconfigured mode is a loopback-only demo. Test with `python3 -m unittest discover -s tests -v`.

## Working now

- Manual Facebook lead capture; name and Sri Lankan phone required initially.
- Caller confirms address, city, product/variant, quantity, COD in LKR and packed weight in grams. Callback/rejection states and duplicate-phone warning.
- Qualification atomically creates one order and booking job. Repeat submission cannot create a second order.
- Internal CSV order sheet export (not a verified FDE import template).
- Manual courier bridge: open portal, book with PP3D reference, record confirmed tracking, attach official PDF.
- Packing queue, official PDF printing through browser/PDF viewer, mark packed.
- Optional caller/admin and packing role passwords; protected routes, CSRF checks and activity history.

## Deliberately not connected

Facebook ingestion, automatic FDE booking/tracking retrieval, status sync, automatic PDF retrieval and unattended printing. The provider interface fails closed; the database booking queue has no worker yet. Do not mistake the scaffold for a working courier integration. See [FDE findings](docs/FDE-INTEGRATION.md) and [architecture](docs/ARCHITECTURE.md).

Upload only official FDE PDFs. The app checks PDF file signature, not label contents; operator must match tracking and recipient. It never invents courier labels or barcodes. One product/variant line per order initially; custom specifications go in notes. Qualified shipment data is frozen; a post-booking edit/cancel workflow is not implemented.

## Online pilot deployment

Use one small persistent Linux server, Flask/Gunicorn, SQLite and private PDF storage. HTTPS reverse proxy plus access gateway with MFA/rate limiting. Both caller and packing site access the same service. Do not use an ephemeral serverless disk.

Set a stable random `OMS_SECRET`, strong distinct `OMS_ADMIN_PASSWORD` and `OMS_PACKER_PASSWORD`, and `OMS_HTTPS=1`. Keep secrets outside Git. Behind the gateway run `gunicorn --workers 1 --bind 127.0.0.1:5055 run:app`. The local demo is not an internet-ready deployment. Gateway configuration, access checks, restore testing and courier commissioning remain required.

Role passwords are for a small pilot behind the gateway; audit identifies roles, not individual employees. Add named users for individual accountability. Stop the app for a consistent backup of the entire ignored `instance/` directory (database and PDFs); encrypt backups and verify restore. Agree customer-data retention before live use.

## Structure

- `oms/__init__.py`: routes, validation, transactions, initial schema.
- `oms/templates/`: caller, courier handoff, packing screens.
- `oms/courier.py`: typed provider boundary and disabled FDE adapter.
- `run.py`: loopback entry point and production app object.
- `tests/`: workflow, duplicate protection, security and isolation checks.
- `docs/`: integration evidence, architecture and implementation stages.
- `instance/`: runtime data, ignored by Git.

No remote GitHub repository or public deployment has been created.
