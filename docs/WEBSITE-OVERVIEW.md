# Website overview

Owner/caller access: `/website-overview`. Refreshes every 30 seconds while visible.

Active visitors means random browser IDs seen within five minutes, not verified people. The storefront sends a heartbeat every 30 seconds only while visible. It counts route openings separately from heartbeats and stores no IP address, form values, URL queries, precise location, or link to a customer account. Browser IDs rotate each Sri Lanka calendar day and are shared across tabs through local storage where available. Cleared/blocked storage and multiple devices affect unique counts. DNT/GPC browsers do not send analytics; bots may still contribute. Referrer host is available only when the browser supplies it.

The same-origin `/api/visit` bridge forwards a bounded, allowlisted payload with the existing server-only OMS token. OMS validates fields, deduplicates view event IDs, stores records on its persistent SQLite volume, and prunes anonymous data older than 30 days during ingestion (hourly maximum frequency). It does not reconstruct historical traffic. A bounded per-visitor rate limiter prevents accidental request loops; these are operational estimates, not fraud-resistant billing metrics.

Website order counts/value are independent of anonymous analytics and include all stored website submissions, including unverified bank payments. Latest 50 orders show review, OMS and courier progress. Parcel counts include all tracked OMS orders and use the latest FDE observations, not immediate courier updates.

Deploy OMS before storefront. No new provider, credentials or Windows installation is required. The storefront source is `../printpro3d-store-online`; production runs the analytics middleware in `server/index.mjs`.
