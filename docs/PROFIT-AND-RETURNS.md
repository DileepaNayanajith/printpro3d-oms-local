# Profit, rack pricing and physical returns

OMS new-order form: choose Hot Wheels rack and Black/White/Gray; quantity 1–2 costs Rs.1,800 each, 3+ Rs.1,750 each, plus Rs.400 per parcel. Server recalculates independent of browser values. Custom orders remain manually priced; website prices and existing orders are unchanged.

Owner-only `/finance` records dated Facebook ads, filament and other expenses; repeated form submits are idempotent. Incorrect entries can be voided without deleting history. Overview shows current-month estimated result. Caller and packing accounts cannot access the financial page.

Estimate = FDE-observed delivered order value (including charged delivery) minus value of previously delivered orders now physically returned, outgoing courier charges, return courier charges, and dated recorded expenses. This is not settlement/cash accounting. Website bank orders count only after payment verification. Manual orders use saved COD. Enter consumed filament cost consistently; purchases may contain unused stock. Do not enter courier charges twice under expenses.

Outgoing courier defaults Rs.400, dated by recorded handover where available or first courier observation; fallback on returned parcels is return-receipt date. Owner can correct outgoing date/charge. FDE first-observed delivery dates can also be corrected. Delivered observations persist as a ledger even if snapshot rows disappear. This does not prove actual delivery date or collected COD. Missing statuses, incomplete sampled history and unverified bank payments are flagged.

Packing02 now has `/packing/returns`: scan PP3D or FDE barcode only when physically received. One return per order; incoming charge Rs.400 plus the existing outgoing charge (not a second outgoing charge). Same/simultaneous scans never double-count. Returns do not create FDE bookings or customer messages. Returned parcels cannot be scanned OUT again; ask the owner to handle any replacement as a new order. Queued dispatch notifications are cancelled for received returns; already-executing sends cannot be recalled.

Home Windows delivered reader historically sampled one page. Use `dist/PRINTPRO3D-Courier-History-Update.zip` to replace only `oms/fde_reports.py` with the 20-page bounded reader. It checks for running station processes, preserves a backup, and keeps login/printer/pairing data. Reopen station and refresh FDE. Installation on Windows has not been executed from the Mac. The endpoint accepts existing station payloads; old stations keep working with incomplete-history warnings.
