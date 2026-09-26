# PRINTPRO3D print, scan and pack

1. Caller uses **Save order & add next** to enter all confirmed orders. Saving does not print.
2. Open **Print labels**, select the ready orders (or Select all), and click **Print selected · 2 per A4**. The screen shows label count and sheet count. Labels are paired left/right on landscape A4. An odd last label leaves one blank half.
3. Check the HP printout. Cut at the middle line and attach the supplied courier sticker in the empty sticker box. Leave the OMS barcode visible.
4. Open **Scan & book**. Scan the OMS PP3D barcode, then the courier CCP barcode. Configure the USB scanner to send Enter after each scan. Without a scanner, select the order and type the courier number.
5. The second scan authorizes one automatic FDE booking using the saved details and rounded-up weight band. The FDE browser must be open and signed in. No packing confirmation is needed to trigger booking. After acceptance, the fields clear and focus returns to the order barcode. Keep scanning while the FDE worker processes orders sequentially. The live list distinguishes queued orders from confirmed bookings.
6. Pack the items using the packing sheet, match the reference and tracking sticker, attach the label, and mark packed after FDE has confirmed booking.

## Start the main computer

Open `start_staff.command` (starts the app and local print worker), then `start_fde.command`. Keep both running. Workers use the same Wi-Fi link. Do not expose the local HTTP service to the internet.

The ignored `instance/printing.json` contains the selected printer and sender details from the supplied template. Fresh installations must configure it before printing. Defaults for this installation use HP_LaserJet_Professional_P1102, A4 landscape, one-sided. A print batch supports up to 200 selected labels. Already queued/printed labels cannot accidentally be included again. The whole batch is one printer job.

## Printer and exception handling

“Sent to printer” means the operating-system spooler accepted the job, not that paper physically came out. If the printer is offline, its spooler can retain the job. Do not request another copy until you have checked the printer queue. Use the order page to request an explicit reprint. Uncertain print attempts never retry automatically. English/Latin label text is supported; unsupported characters or oversized text require correction rather than printing unreadable labels.

FDE timeouts or unexpected responses require reconciliation before retrying. The worker accepts only the observed fresh “Success!” / “Add Successfully!” response as booking success. A real authorized order CCP17778579 was successfully submitted on 26 September 2026; do not use it for repeat submission tests.

The template is the user's parcel label, not an automatically downloaded official FDE PDF. Official PDFs can still be attached separately if needed. Actual USB-scanner operation and physical paper output must be verified on the user's hardware.

## Customer SMS setup pending

New confirmed orders prepare one processing message. Once a packed parcel is actually handed to FDE, **Handed to courier · mark dispatched** prepares a second message with its tracking number. Booking a parcel alone does not claim it has been dispatched. The SMS page shows prepared messages and invalid mobile numbers. No SMS transport or provider is configured yet, so nothing is sent. Do not release held setup messages retroactively without checking their age and current order status when activating a provider. Provider credentials belong in ignored local settings, never Git or chat.
