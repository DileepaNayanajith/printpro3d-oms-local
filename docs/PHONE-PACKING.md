# Phone packing and courier handover

Use the online OMS `/login` with `packing02`. The account is a packer with `packing_only=1`; server-side checks allow only packing, its scan endpoint, logout and static assets. Other staff permissions are unchanged.

At physical courier handover, open the phone camera and scan the Code 128 **PP3D order barcode**. A booked parcel with a printed label is marked dispatched and recorded once with staff name and UTC timestamp. This scan also confirms physical packing, so the earlier separate Packed click is optional for this scanner. Existing manual packing/dispatch controls retain their checks and feed the same handover record. This is a local staff handover record, not a new FDE status report or booking.

After each scan, the camera stops and shows order ID, customer name, COD and success/duplicate status. Press Scan next parcel to resume. Camera images are decoded on the device and not uploaded. Manual PP3D entry is available if camera permission or focus fails. Use the ordinary phone browser over HTTPS. Actual phone camera performance must be checked on the packing worker's device.

The owner/caller can open `/handovers` or Overview > View parcel handover counts, select a Sri Lanka date and see parcel count, staff and times. Counts are parcels, not rack quantities. Daily counts begin with recorded handovers; older dispatched parcels remain in the all-dispatched total and rescanning them does not falsely count them today.

The `parcel_handovers.order_id` primary key and immediate transaction prevent duplicate counts across simultaneous devices and retries. A failed response can be retried with the same barcode without re-dispatching. No live parcel was used for testing.

Vendor scanner: @zxing/library 0.21.3, Apache-2.0; official source https://github.com/zxing-js/library . Distribution and license are vendored under `oms/static/vendor/` for same-origin loading.

Validation: 102 automated tests, JS syntax check, and local fixture browser flow. Password is stored only in private `instance/packing02-access.txt`; the cloud receives only a password hash. Cloud startup creates the restricted user once and never overwrites an existing password or enables a disabled account.
