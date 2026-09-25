# Current packing-to-FDE flow

1. Caller saves a confirmed order.
2. Packing checks the parcel, enters the CCP sticker and weight, and clicks **Confirm packing & book with FDE**.
3. The worker fills and verifies the form, then submits once. No second approval is required.
4. A fresh FDE **Success! / Add Successfully!** receipt marks the order booked with the assigned tracking number.
5. Timeout, logout or an unexpected response requires attention; never submit the same parcel again without checking FDE.

Run `start_fde.command` on the main computer and keep its browser open and signed in. This launcher enables submission for packing-confirmed orders. Preparation-only orders do not gain submission permission automatically. The official label PDF download/attachment remains manual.

Live verification: on 26 September 2026, the owner confirmed order PP3D-000002 was packed and ready. Its CCP17778579 booking received the FDE success receipt. The updated automated receipt detector is covered by tests; do not create duplicate live bookings for testing.

## Earlier pilot reference

# PRINTPRO3D — staff pilot

Use the staff link supplied by the owner while connected to the same trusted work Wi-Fi. The owner computer and both app/browser processes must stay running. This pilot uses HTTP on the local network; do not open router ports or share it over public Wi-Fi. Use an HTTPS gateway before internet access.

## Caller

1. Call and qualify in Meta Business Suite as usual.
2. Sign into OMS with your caller username and password.
3. Enter the confirmed delivery details once. Check phone, address, FDE city, product/variant, quantity, total COD and packed weight.
4. Select **Save confirmed order → packing**. Use **Save draft** if information is missing.
5. Review the FDE worker form when ready. Filling is not submission. During the pilot, verify the actual FDE parcel record before confirming tracking in OMS.
6. Save the official FDE label PDF and attach it to the order.

## Packing

1. Sign in with your packing account. The **To pack** list shows active orders.
2. Match product and quantity to the physical parcel.
3. Scan/type the unused assigned CCP sticker number and confirm the FDE kg band. Queue automatic form filling.
4. Wait for courier confirmation and the official waybill.
5. Open/print the waybill, check recipient and sticker match, then mark packed.
6. Use **Already packed** to find completed work. Never dispatch TEST ONLY entries.

## Owner

- Staff passwords are in local `instance/staff-access.txt`; distribute only the appropriate account password. This file is excluded from GitHub.
- Add individual accounts with `python manage.py add-user username --role caller` or `--role packer`. Passwords are entered privately at the prompt and stored hashed.
- Disable a departing user with `python manage.py disable-user username`.
- The two sample staff accounts are station accounts. Create one username per worker if individual audit is required.
- Double-click `start_staff.command` to launch the local staff service on macOS, and `start_fde.command` for FDE preparation. Do not start a second copy if already running.
- Keep the dedicated FDE browser open after login. Closing it can lose the portal session.
- If **Needs review** appears, search FDE by exact waybill/order reference before retrying. Ask the owner if data needs correction; qualified-order editing/cancellation is not implemented yet.

## Before everyday dispatch

Live auto-fill is verified. A controlled real booking, success reconciliation and official label/printer check are still required. Automatic submit remains off. This is a staff pilot, not yet unattended courier dispatch.
