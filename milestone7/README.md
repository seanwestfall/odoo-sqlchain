# Milestone 7 — release candidate and pilot validation

**Engineering package available; real-user and independent-installation gates outstanding.** This is a self-hosted testnet prototype, not a production release. The new clean installation runs on port 8073, separately from M0–M6. It starts with execution paused and Arc disabled, and installs no signer service or Circle credentials.

## Supported installation target

Validated on Apple Silicon macOS, native PostgreSQL **16.15**, CPython **3.12.0**, Node **24.19.0**, and Docker Desktop with the Odoo image pinned in `compose.yaml`. `dependencies.json` records versions and lockfile digests. PostgreSQL versions other than 16 and Linux deployments are not validated by this release candidate. Do not claim a broader compatibility matrix.

Prerequisites: native PostgreSQL 16 including `pg_config`/PGXS (`brew install postgresql@16`), Python 3.12, Node 24, Git, and running Docker Desktop. Run as an ordinary OS user with permission to install extension SQL files in the chosen PostgreSQL installation; do not run PostgreSQL as root.

The working repository is `/Users/sean/Projects/chainsql`; the old `/Users/sean/Projects/odoo` runtime is retained. Milestones 5–7 are included in the repository. Alternatively, use the generated source package plus its SHA-256 file; it includes milestone source but no Odoo history, dependencies, databases or secrets.

```sh
# Clone the published source:
git clone --recurse-submodules https://github.com/seanwestfall/odoo-sqlchain.git
cd odoo-sqlchain
# Source-package recipients instead extract the package and enter its chainsql directory.
python3 milestone7/scripts/fetch_odoo.py
python3.12 -m venv .local/release-venv
.local/release-venv/bin/python -m pip install --require-hashes -r milestone7/requirements-macos-arm64.lock
npm ci --ignore-scripts --prefix milestone0/wallet
npm ci --ignore-scripts --prefix chainsql/x402
.local/release-venv/bin/python milestone7/scripts/bootstrap.py
```

The wheel lock is specifically for macOS 14+ arm64 / Python 3.12. Do not remove hash checking to force an unsupported platform. Node dependencies have their existing npm lockfiles. The upstream Odoo commit is `7bbce824a1897a912441a7f0511ffec505cbe1d5`; its runtime dependencies are supplied by the digest-pinned image.

Open `http://localhost:8073`. Login is `admin`; obtain the generated password locally from `.local/release/credentials.json`. This is a fresh installation, not a clone of the M5 sample bills. The reviewer walkthrough uses the existing sample instance separately. Native database port is 55437; private socket/state are in `.local/release`. `PG_BIN` overrides the PostgreSQL binary directory. Bootstrap never touches the old 55432 cluster. Local socket administration trusts the OS user and is protected by the private directory; TCP roles have separate random credentials.

## Upgrade and ordinary operation

Stop Odoo and every executor before upgrading; take a consistent backup first. The bootstrap is repeatable: on an initialized release database it applies SQL upgrades/ACLs and upgrades installed integration addons, preserving data and generated credentials. It deliberately leaves execution paused. Native migrations are 0.1.0 → 0.2.0 → 0.2.1 → 0.3.0 → 0.4.0; unknown versions and downgrades are rejected.

```sh
# Upgrade the local release candidate (workers must remain stopped):
.local/release-venv/bin/python milestone7/scripts/bootstrap.py
# Ordinary restart does not reinstall modules:
/opt/homebrew/opt/postgresql@16/bin/pg_ctl -D "$PWD/.local/release/pgdata" -l "$PWD/.local/release/postgres.log" -w start
docker compose -f milestone7/compose.yaml up -d odoo
# Stop the app before the native database:
docker compose -f milestone7/compose.yaml stop odoo
/opt/homebrew/opt/postgresql@16/bin/pg_ctl -D "$PWD/.local/release/pgdata" -m fast stop
```

Skip `pg_ctl start` if it is already running. For a separately managed host, `scripts/upgrade_sql.py --socket SOCKET --port PORT --database DATABASE` applies the SQL upgrade with the local administrator `m0_admin`; provision roles first. Do not use it on an unreviewed business database. Use Odoo `-u` for addon upgrades; never update accounting records through direct SQL.

## Self-hosting boundary

The tested self-host is an always-on Mac using the commands above. Bindings remain loopback; reviewers can use an authenticated SSH local forward to port 8073. Do not expose PostgreSQL, the seller, an admin login or a raw Quick Tunnel as a production deployment. An Internet deployment additionally needs an administered HTTPS/identity gateway, appropriate Odoo `proxy_mode`, verified forwarded headers, access policy, persistent disks, host patching and backup monitoring. These are deployment prerequisites, not controls this package silently installs. A Linux host needs its own tested networking/PGXS/wheel configuration before it is supported.

`secrets.env.example` contains only blank placeholders and explains separate service files. Odoo and the delegated worker must never receive the signer encryption key, Circle entity secret, policy-role membership or administrator socket. The owner/policy roles are NOLOGIN. Host/database administrators and the restricted signer remain trusted: there is no general on-chain budget contract. The externally signed document publisher is operator-only. Agent/model access is limited to authorized addon actions, not these installation/admin scripts.

`testnet.json` documents the fixed adapter networks and units; it does not override their allowlists. Arc token transfers use 6-decimal ERC-20 USDC and 18-decimal native fees. x402 uses Base Sepolia exact/EIP-3009. Never replace testnet configuration with a mainnet endpoint and assume the policy remains valid.

## Pause, rotation and recovery

A policy operator pauses new signing/dispatch with `chainsql.set_pause_v1(true)` and disables Arc with `chainsql.enable_arc_v1(false)`. Stop executors too. Pausing cannot revoke a transaction already signed or transmitted. Preserve its reservation, exact signed bytes, hash/provider ID and journal. Reconciliation must still be allowed while execution is disabled.

For wallet rotation: disable the old tenant/wallet mapping through `set_wallet_v1`, inventory/reconcile all existing authorizations and nonce reservations, register the new wallet under a distinct mapping, approve new requests explicitly, and enable dispatch only after review. Never migrate an outstanding obligation by merely changing its wallet or recreating its request. Tests show old-wallet dispatch is blocked and its existing reservation is retained. Circle credential/entity-secret rotation itself is a separate provider-managed procedure and has not been exercised here.

Provider subprocess calls are bounded (Arc 90 seconds, resource/seller 65 seconds); fixed RPC transports disable automatic retries and use finite timeouts. A timeout is uncertain, not permission to sign again. Forced process termination tests cover the durable seller dispatch claim. A crash between claiming and actual transmission may require manual recovery rather than automatic progress.

## Backup / restore runbook

1. Pause execution, disable Arc and stop **all writers**: Odoo, worker, signer, observer, seller and document publisher. Reconciliation observations may be completed before taking the snapshot, but cannot mutate journals during it.
2. Capture a custom-format PostgreSQL dump, the matching Odoo filestore, exact Arc/resource/seller journals (SQLite backup API or stopped-process copy including WAL), document/seller encryption keys, signer configuration, and provider recovery material. Record file checksums and protect backup/key copies separately with encryption and access control. A database-only backup is incomplete.
3. Restore into a new isolated database with workers disconnected. Provision the same roles separately. Install matching extension SQL files. Use `upgrade_sql.py --empty-restore-target` only on an empty target to create extension objects/ACLs without seed runtime control rows. Precreate `unaccent`, `pg_trgm`, and mark `public.unaccent(text)` IMMUTABLE before restoring Odoo's indexes.
4. Restore the dump with `pg_restore --exit-on-error`, omitting only the already-created `SCHEMA - chainsql` TOC entry. Restore the filestore under the **target database name**, preserving Odoo ownership. Restore original keys and exact journals; do not generate replacements. Verify checksums and original attachment bytes.
5. Explicitly pause/disable execution again after restoring control rows. Upgrade addons using Odoo's `-u` in `--stop-after-init --no-http` mode. Reconcile every possibly dispatched operation by original hash/authorization/provider ID, including actions newer than the database backup. Missing journal/provider evidence requires human review and keeps execution blocked.
6. Review reservations, nonce high-water marks, uncertain count and accounting linkage before an operator re-enables execution. Receipt confirmation alone does not force a bill Paid. Re-run the web asset check; a copied database without its filestore can render blank.

`verify_restore.py` executes the full Odoo/filestore portion with a pending **probe**, plus addon upgrade in a new target. Native M3 separately verifies pending signed authorizations, nonce state and original-hash reconciliation with a synthetic provider. These are separate exercises, not a claim that a live multi-service production restore has been validated. Private backup directories and failed disposable targets are retained for inspection.

## Validation and evidence

```sh
.local/release-venv/bin/python milestone7/scripts/verify_release.py
.local/release-venv/bin/python milestone7/scripts/verify_restore.py
.local/release-venv/bin/python milestone7/scripts/test_process_recovery.py
.local/release-venv/bin/python milestone7/scripts/test_provider_bounds.py
.local/release-venv/bin/python milestone7/scripts/test_events.py
.local/release-venv/bin/python milestone7/scripts/check_web.py
.local/release-venv/bin/python milestone7/scripts/metrics.py --dataset synthetic --output .local/release/metrics.json
```

`evidence/native-m3.json` has 33 native checks; `native-m4.json` has 23. `restore.json` records six full Odoo restore/upgrade checks. Separate tests cover SIGKILL recovery, two timeout boundaries, and event identity/dataset isolation. `web.json` verifies authenticated HTML plus actual JS/CSS responses. Earlier milestone company-access and signer restrictions remain separately documented; they are not new live customer evidence. Metrics from synthetic load are explicitly labeled.

Use [the walkthrough](WALKTHROUGH.md) for review and [the pilot register](PILOT.md) for real-user acceptance. Outstanding release gates: independent developer installation, genuine business-user completion, permissioned/redacted evidence and ongoing pilot observation. M6 live seller settlement and optional live Arc document publication also remain unvalidated. Do not promote any of these to completed merely because automated checks pass.
