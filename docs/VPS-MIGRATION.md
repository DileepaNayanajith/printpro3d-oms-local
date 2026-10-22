# PRINTPRO3D VPS migration runbook

Status: preparation only. No VPS purchased, DNS switched, or production data moved.

## Provision

Use a fresh Ubuntu LTS x86-64 server. Target at least 2 vCPU / 4 GB RAM;
8 GB is preferable if website builds and Coolify run together. Check live
availability and the complete server, IPv4, backup and tax price before purchase.
Do not reuse the unrelated Natural Foliage server/project.

Install Coolify following https://coolify.io/docs/start-with-self-hosted .
Use SSH keys, restrict administrative access, and configure HTTPS. Complete the
initial admin registration immediately. Back up Coolify's encryption key privately.

## OMS staging

Create /srv/printpro3d/oms on the VPS before deployment. Connect this private
GitHub repository to Coolify using minimal repository access. Select production,
Docker Compose, base directory / and /compose.coolify.yaml. Route a temporary
HTTPS subdomain to service oms, internal port 8080. No host port is published.

Supply secrets in Coolify, never Git. OMS_SECRET must be at least 32 characters.
For an EMPTY staging database, set a temporary OMS_OWNER_PASSWORD (16+ characters)
and sender address/phone. Leave live booking disabled and SMTP unconfigured.
Do not pair a real station or send real customer messages during staging.
Verify /healthz, owner login and synthetic order/label flows.

## Backup and final cutover

Before moving production, inventory the COMPLETE Railway persistent volume and
all environment variable names privately. The existing cloud_transfer.py is a
limited export (database, sender settings, PDFs); it is NOT a complete backup of
uploads, website tokens or all current queues. Do not rely on it alone.

1. Take an independent backup and restore rehearsal before scheduling downtime.
2. Pause order entry AND website checkout, stop home station workers, and pause
   scheduled/background senders. Record outstanding print/FDE/message jobs.
3. Stop the source app for the final consistent volume snapshot. Preserve the
   whole volume, including uploads and SQLite sidecar files. Never copy only a
   live SQLite database file. Keep an encrypted off-server copy.
4. Restore to an empty target directory. Verify SQLite integrity, order counts,
   last order IDs, files, users and settings. Never overwrite staging data with
   the source app running; remove staging only after confirming it is disposable.
5. Review uncertain/in-flight jobs before starting workers; do not replay FDE,
   print, WhatsApp or email sends. Expire stale station control commands. Decide
   explicitly whether to re-pair stations; keep them stopped until target verified.
6. Configure matching integration secrets, website OMS URL, CORS/allowed origins
   and any callback URLs after inspecting the website's actual configuration.
7. Switch OMS domain and station URL, then website checkout destination. Only one
   OMS may accept writes. Verify a controlled order end-to-end before reopening.
8. Keep Railway data intact for rollback. If the target has accepted new orders,
   reconcile those writes before rollback; simply switching DNS loses updates.

Website deployment is a separate Coolify resource. Inspect its repository,
Dockerfile, database/uploads and environment before migrating printpro3d.lk.

## Ongoing recovery

Schedule daily consistent SQLite snapshots plus uploads/config backups to encrypted
storage outside this VPS. Retain daily and weekly copies and test restore monthly.
Provider snapshots supplement, not replace, application backups. Add external
uptime alerts. Document who installs OS/Coolify updates and checks backup failures.
Do not remove Railway until checkout, station, printing and recovery tests pass.
