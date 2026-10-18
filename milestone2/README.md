# Milestone 2 — Payment boundary before live execution

The native extension is **0.2.1**, with the explicit command:

```sql
SELECT chainsql.request_transfer_v1(approval_uuid, immutable_snapshot_jsonb, idempotency_key);
```

This milestone is complete for the **local settlement pilot**. The Odoo adapter, separate worker, restricted signer, authoritative simulator and observer have been exercised together. Live network execution remains disabled in both the SQL snapshot validator and signer. No Circle/Arc key is used, no blockchain funds move, and no Odoo payment/accounting entries are created.

## What is enforced

| Requirement | Pilot enforcement mechanism |
|---|---|
| Immutable request | Independently issued SQL approval contains the exact 14-field JSON snapshot. The submission must match it exactly. Table triggers reject snapshot changes; application/worker roles have no table-write privileges. |
| Independent approval | Only the `chainsql_policy` role can issue approval, change wallet permissions/budgets, or unpause. It is **NOLOGIN**, with no membership granted to Odoo, worker, signer or observer. Odoo approval alone cannot authorize a transfer. |
| Value and fee reservation | One PostgreSQL transaction locks the execution gate and checks/reserves both the company budget and source-wallet budget before returning a signing claim. Missing budgets fail closed. |
| Per-operation limits | Both company and wallet per-operation value/fee limits apply when reserving. Cumulative limits include all outstanding reservations plus observed spend. These are lifetime budgets, not an automatically resetting daily allowance. To withdraw an already reserved approval, revoke it or pause execution; lowering a per-operation limit alone governs future reservations. |
| Concurrent workers | A shared row-lock order serializes control/reservation transitions. Company/wallet caps cannot be exceeded by concurrent claims. This deliberately favors correctness over throughput for the pilot. |
| One payable attempt | One active transfer per tenant/business obligation, one immutable authorization per transfer, and a stable preparation ID `transfer-v1:<UUID>`. A settled obligation cannot acquire another payable revision. |
| Stale owners | Claims have a 30-second lease, random token and monotonically increasing fence. Sign, save, dispatch and simulator acceptance check the current fence. A takeover reuses the original authorization, never creates a different payable attempt. |
| Save before send | The signer persists AES-256-GCM encrypted authorization bytes, commits, then dispatches. SQL rejects dispatch in the authorization's saving transaction. A save failure stops execution. |
| Restricted signing | The service accepts only operation UUID/token/fence. It constructs and signs the independently approved snapshot; callers cannot supply raw bytes, an amount, destination, asset, policy or RPC URL. The key is an Ed25519 **simulator key**, not an EVM wallet key. |
| Secret isolation | Only the signer role can access encrypted authorization material through dedicated functions. The worker mounts no signer/observer/policy credentials. No ordinary view/status response or Odoo chatter contains authorization bytes. Signer statement/parameter logging is disabled, and the service does not log bodies or secret-bearing exceptions. |
| Source-data changes | Odoo-owned database triggers revoke SQL approval on bill amount/residual, company, vendor, currency, state, reference, due-date or selected-wallet changes, and on wallet recipient/network/asset/version/status/vendor changes. Stored accounting recomputations are covered, not only ORM `write()` calls. Revocation commits or rolls back with the source edit. |
| Dispatch checks | The SQL boundary rechecks approval/head revocation, validity window, current source-wallet permission and execution pause before signing/saving/dispatching/accepting. |
| Observed spend | Only the observer can reconcile the simulator's authoritative ledger. Settlement converts reserved value plus the actual fee to spend exactly once, releasing unused fee allowance. |
| Cancellation | Unsigned requests can release reservations. Once authorization exists, cancellation retains them and enters reconciliation. A settlement already accepted still counts as spend; any refund is a separately approved compensation. |
| Safe release after expiry | Only `mock:local` is supported. Its acceptance and expiry proof share the same database clock, gate lock and authoritative ledger, so expiry without settlement proves the old authorization can no longer settle. This proof is **not** valid for a generic live-chain adapter. |

Both value and fees use simulated USDC integer atomic units at **6 decimals** (`mock-usdc-6`). The simulator charges exactly **1 atomic unit** per accepted transfer; requests with a lower fee ceiling cannot settle. This convention is explicit and does not copy Arc's native 18-decimal gas interface. Atomic amounts are decimal strings in the snapshot and exact PostgreSQL numeric integers in budgets. No float arithmetic is used by the boundary.

The snapshot fields are `tenant`, `business_reference`, `request_revision`, `source_wallet`, `destination`, `network`, `asset`, `interface`, `amount_atomic`, `fee_ceiling_atomic`, `policy_version`, `approval_identity`, `valid_from`, and `valid_until`. UTC timestamps ending in `Z` are required, with a validity window no longer than 24 hours. The issuer's actual database session identity is also audited separately from the supplied business approval identity.

## Trust boundary and live-execution limits

The delegated model/worker operates with the worker credential and the narrow service API. It cannot edit controls or read signing keys. The Odoo role can submit independently approved snapshots and revoke/cancel authority, but cannot grant it. Company isolation in the Odoo UI is additionally enforced by the existing global record rules and server-side access checks. A single Odoo database login represents multiple companies, so those ORM rules remain part of the ERP adapter's trust boundary.

The trusted computing base is the PostgreSQL extension owner/administrator, policy operator, restricted signer service and simulator/observer implementation. Host administrators and the development agent that can edit source files or run administrator commands are **outside** the delegated-worker threat model. A read-only container mount does not protect against a privileged host editor. Before delegating real funds, deploy the signer/policy administration in a separately administered environment or an appropriate hardware/contract-enforced boundary that the model's execution environment cannot modify.

This pilot does not claim smart-contract enforcement on Arc, EIP-3009 execution, x402 settlement, a live custody integration, live-chain finality handling, or proof that an expired live-chain authorization was never included. In particular, an expired signature on a live chain may already have settled before expiry. Live release requires authoritative receipt/finality or nonce/authorization-consumption evidence. Until that adapter and enforced signer path are validated, the code rejects live-network snapshots rather than falling back to arbitrary RPC calls.

## Setup and start

Prerequisite: the native PostgreSQL/accounting-only setup and Milestone 1. Run from the repository root:

```sh
python3 milestone2/scripts/setup.py
# This installs the PGXS SQL files, upgrades 0.1.0 → 0.2.0 → 0.2.1,
# creates restricted roles and private simulator keys, and reapplies grants.

docker compose -f milestone0/compose.yaml stop odoo
docker compose -f milestone0/compose.yaml run --rm odoo \
  odoo -i chainsql_transfer_boundary --stop-after-init --no-http

docker compose -f milestone0/compose.yaml -f milestone2/compose.yaml \
  --profile boundary up -d odoo transfer-boundary
```

For existing installations use `-u chainsql_transfer_boundary` for view/model updates. The addon installs its adapter triggers on initial installation and removes them on uninstall. The old Milestone 1 mock worker remains separate.

The service has no published host port. The worker calls it on the private Docker network. It uses the pinned Odoo image (Python, psycopg2 and cryptography 41.0.7). The container filesystem is read-only, capabilities are dropped, and privilege escalation is disabled. Its only writable state is in native PostgreSQL. Simulator secrets are stored in ignored `.local/milestone2/` with directory mode 0700 and file mode 0600; they are mounted only in the boundary service. Do not delete or regenerate these keys while prepared authorizations exist.

A fresh boundary starts paused. Only a policy operator should enable it and issue policy approvals. The operator-only [demo provisioning script](scripts/provision_demo.py) configures the labelled **mock-only** development bill and is never mounted in the worker. Its approval identity explicitly identifies the acceptance harness; it is not presented as a real human production payment approval.

For this demo, the company and wallet each have a value budget of 100 simulated USDC, a fee budget of 0.1, per-operation value cap of 50, and per-operation fee cap of 0.01. The bill is 30 simulated USDC with a 0.01 fee ceiling. These numbers are fixture controls, not production policy recommendations.

## Odoo workflow

Open the bill's ChainSQL operation and select **Transfer boundary**.

1. Prepare/approve the current bill request using the Milestone 1 workflow.
2. Have the independent policy operator issue approval for the exact transfer snapshot.
3. Click **Request bounded test transfer**. Odoo calls the restricted SQL command in its own transaction.
4. Run the worker with the returned UUID:

```sh
docker compose -f milestone0/compose.yaml -f milestone2/compose.yaml \
  run --rm transfer-worker TRANSFER_UUID
```

5. Click **Refresh transfer status**. Only public status/snapshot/receipt metadata is synchronized into Odoo.

After a lost response or cancellation, reconcile the same UUID:

```sh
docker compose -f milestone0/compose.yaml -f milestone2/compose.yaml \
  run --rm transfer-worker TRANSFER_UUID --reconcile
```

For an incomplete, still-valid prepared request, a worker can reclaim after its 30-second lease expires and retry the exact saved authorization. Do not create a new obligation to work around uncertainty. After a cancelled/expired request, a fresh request revision and independent approval are required. The current UI retains the historical operation and does not automatically renew expired payment authority. Fresh revisions after cancellation/expiry require operator-reviewed integration commands or a genuinely changed, revalidated bill; do not alter a real bill merely to force a retry.

## Tests and evidence

```sh
python3 -m venv .local/milestone2/venv
.local/milestone2/venv/bin/pip install -r milestone2/requirements-test.txt
.local/milestone2/venv/bin/python milestone2/scripts/verify.py
.local/milestone2/venv/bin/python milestone2/scripts/verify_odoo.py
```

The native suite creates unique `chainsql_m2_verify_*` and `chainsql_m2_restore_*` databases. It verifies concurrency, caps, fencing, durable encryption, denied role access, fail-closed persistence, dispatch control changes, cancellation/reconciliation, and native dump/restore. Lease takeover uses explicit test-only expiry injection in its disposable database. Authorization-save failure is injected with a temporary rejecting trigger.

The Odoo suite briefly stops/restarts the development services to clone the native database, then tests only the clone. It verifies transactional submission/rollback, company access, balance recomputation and recipient invalidation, and signer refusal after a committed Odoo edit.

- [58 native boundary checks](evidence/integration.json)
- [8 Odoo integration checks](evidence/odoo-integration.json)
- [35 Milestone 1 regression checks](../milestone1/evidence/integration.json)
- [Browser and service walkthrough](evidence/walkthrough.md)
- [Token accounting](evidence/token-usage.json)

## Backup and restore

Extension-owned runtime tables are included using `pg_extension_config_dump`. The upgrade to 0.2.1 changes audit identities to UUIDs so restores do not depend on an omitted extension-owned identity-sequence counter.

The test restores into a separate database with the extension precreated under `chainsql_owner`, filters the duplicate schema entry from the pg_restore TOC, restores with `--exit-on-error`, and **sets the restored execution pause before allowing workers to use it**. It checks exact encrypted bytes, budget balances, owner and decryption with the retained external key.

Back up signing/encryption keys separately and securely; the database dump does not contain them. Never run a restored copy and the original as independent live execution systems against the same funds. Restoring a snapshot cannot establish the current state of a live network. The pilot restore test is confined to the local simulator.

## Implementation references

The locking design uses PostgreSQL's transaction-scoped row locks; see [PostgreSQL 16 explicit locking](https://www.postgresql.org/docs/16/explicit-locking.html). The signer uses the documented [AES-GCM authenticated encryption API](https://cryptography.io/en/41.0.7/hazmat/primitives/aead/) with random nonces and transfer identity as associated data, and [Ed25519 signing/verification](https://cryptography.io/en/41.0.7/hazmat/primitives/asymmetric/ed25519/). These primitives do not by themselves establish live payment safety; the application/SQL boundaries above are also required.
