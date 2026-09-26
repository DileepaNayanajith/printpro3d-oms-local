# PRINTPRO3D print, scan and pack

1. Caller saves a confirmed order. One A5 parcel label is queued automatically on the left half of a landscape A4 sheet. Drafts do not print. Repeated saves cannot queue duplicate labels.
2. Check the HP printout. Cut at the middle line and attach the supplied courier sticker in the empty sticker box. Leave the OMS barcode visible.
3. Open **Scan labels**. Scan the OMS PP3D barcode, then the courier CCP barcode. Configure the USB scanner to send Enter after each scan. Without a scanner, select the order and type the courier number.
4. The second scan authorizes one automatic FDE booking using the saved details and rounded-up weight band. The FDE browser must be open and signed in. No packing confirmation is needed to trigger booking.
5. Pack the items using the packing sheet, match the reference and tracking sticker, attach the label, and mark packed after FDE has confirmed booking.

## Start the main computer

Open `start_staff.command` (starts the app and local print worker), then `start_fde.command`. Keep both running. Workers use the same Wi-Fi link. Do not expose the local HTTP service to the internet.

The ignored `instance/printing.json` contains the selected printer and sender details from the supplied template. Fresh installations must configure it before printing. Defaults for this installation use HP_LaserJet_Professional_P1102, A4 landscape, one-sided. This version uses one half of each sheet; it does not batch two orders onto one page.

## Printer and exception handling

“Sent to printer” means the operating-system spooler accepted the job, not that paper physically came out. If the printer is offline, its spooler can retain the job. Do not request another copy until you have checked the printer queue. Use the order page to request an explicit reprint. Uncertain print attempts never retry automatically. English/Latin label text is supported; unsupported characters or oversized text require correction rather than printing unreadable labels.

FDE timeouts or unexpected responses require reconciliation before retrying. The worker accepts only the observed fresh “Success!” / “Add Successfully!” response as booking success. A real authorized order CCP17778579 was successfully submitted on 26 September 2026; do not use it for repeat submission tests.

The template is the user's parcel label, not an automatically downloaded official FDE PDF. Official PDFs can still be attached separately if needed. Actual USB-scanner operation and physical paper output must be verified on the user's hardware.
