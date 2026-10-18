# Milestone 1 — Odoo bill → transactional mock worker

Implemented for the disposable `chainsql_m0` installation at <http://localhost:8070/odoo/vendor-bills>.
The original BOM instance on port 8069 is separate. Circle/Arc credentials are not used by this milestone.

## Start or reproduce

Complete the native PostgreSQL and accounting-only setup in [Milestone 0](../milestone0/README.md) first. This milestone requires its installed `chainsql` extension 0.1.0 and dedicated database roles. It adds no Purchase or Inventory dependency.

From the repository root:

```sh
python3 milestone0/scripts/native_setup.py
python3 milestone1/scripts/configure.py
# Stop the accounting server while updating its modules.
docker compose -f milestone0/compose.yaml stop odoo
docker compose -f milestone0/compose.yaml run --rm odoo \
  odoo -i chainsql_account --stop-after-init --no-http
# For an existing installation use -u chainsql_base,chainsql_account instead of -i.
docker compose -f milestone0/compose.yaml --profile mock up -d
```

The two addons live in `chainsql/odoo_addons`, mounted read-only at `/mnt/chainsql-addons`. The startup config includes that path alongside `/mnt/extra-addons`. Odoo core is unchanged. `chainsql_base` contains the ERP-independent operation/wallet models; `chainsql_account` inherits vendor bills. `res.partner` provides a view of company-scoped wallet records. `account.payment` integration is deferred.

The mock worker is a separate container using the same pinned Odoo image for Python/psycopg2. Its only credential is the restricted `chainsql_worker` SQL login, mounted from ignored `.local/milestone0/worker.json`. It cannot read or modify Odoo accounting tables. Native PostgreSQL remains outside Docker.

## Use in Odoo

The development admin already has the **ChainSQL / Test approver** role. Other users need the usual Invoicing permissions plus **Test operator** or **Test approver**. The approver role includes operator capabilities; it does not bypass company record rules.

1. In the ChainSQL app, open **Company test wallets**. Create a wallet for the exact company and vendor, with a local simulation recipient identifier, then **Approve test wallet**. A shared contact has separate wallet approvals for each company. Editing a wallet clears its approval and invalidates pending requests.
2. Open a posted USD vendor bill with a positive outstanding balance. On its **ChainSQL** tab, an approver selects the wallet.
3. **Prepare test request** captures the immutable company, bill/vendor references, due date, amount, asset, network, recipient, wallet version and policy version. This opens the request.
4. An approver reviews it and clicks **Approve test request**. An operator can then click **Queue test operation**, either here or on the bill.
5. Once the request transaction commits, the worker can see it. Click **Refresh mock result** to let Odoo verify and display the simulated receipt. The bill tab links to the same operation.

The amount is the outstanding USD balance, represented as an integer string with **6 decimal atomic units**. For example, USD 30.00 produces `30000000` simulated USDC units. This is an explicit mock convention, not an Arc native-unit adapter or a claim of USD/USDC market equivalence.

The operation shows the request revision/fingerprint, SQL operation UUID after queueing, company, bill reference, proposed amount/asset, approved recipient/network, recommendation, explanation, approval actor/outcome/current validity, policy version, execution state, mock receipt, resource purchases (empty), and review reason. Request fields cannot be changed through ORM/RPC writes.

Bill and wallet edits invalidate pending approvals. Balance changes caused by accounting recomputation also make **Approval still valid** false; queueing always compares the current snapshot again under locks. Prepare and approve a new revision after changes. Historical snapshots and their recorded approvals remain available for audit.

## Transaction and concurrency behavior

Odoo inserts its immutable request and calls `chainsql.enqueue_probe` using its own transaction cursor. The action never commits or performs network calls. The existing extension's `probe` transport carries a versioned `mock-v1` payload; this is deliberately not a production payment queue.

Bill-row locking, a unique bill/revision constraint, and the SQL idempotency key protect repeated requests. Odoo's normal serialization retry mechanism handles competing transactions. Repeated queue clicks on an unchanged request return the same operation UUID. A rollback removes the SQL job and the corresponding Odoo queue-state change.

The worker claims and completes one job inside a single transaction. A process failure before commit rolls back both actions, leaving the job available for retry. Concurrent workers use `SKIP LOCKED`. Results are validated by Odoo against the immutable request before being displayed. The worker never writes Odoo tables, and result synchronization does not create payments or accounting entries.

Only the versioned local simulation network is accepted. No external HTTP, x402 purchase, signing, token transfer, or resource charge is performed. All receipts are explicitly prefixed `mock:`. Production payment retries, reconciliation, wallet provisioning, and a separate dashboard are later milestones.

## Repeatable acceptance tests

```sh
python3 milestone1/scripts/verify.py
```

This briefly stops the 8070 Odoo container and its mock worker to clone the native database, restarts the services, then runs the checks in a uniquely named `chainsql_m1_verify_*` clone. It creates a fresh real vendor bill and test users in that clone. Clones are retained for inspection. Evidence is written to `milestone1/evidence/integration.json`.

The suite checks authorized preparation/approval, immutable snapshots, rejected forged writes, company isolation (including a shared contact and forged allowed-company context), wallet-change restrictions, the worker's lack of Odoo-table permissions, uncommitted-job invisibility, rollback, four concurrent queue requests producing one obligation, post-commit worker execution, validated result synchronization, unchanged accounting, and invalidation after wallet/bill/balance changes.

To create the labelled development bill used in the browser walkthrough (idempotent):

```sh
docker compose -f milestone0/compose.yaml run --rm -T odoo \
  odoo shell --no-http < milestone1/scripts/seed_demo.py
```

It creates only the labelled demo bill and its approved mock wallet; prepare, approve and queue the request through the UI.

## Evidence

- [Integration checks](evidence/integration.json)
- [Browser walkthrough](evidence/browser-walkthrough.md)
- [Native installation/role/backup evidence from Milestone 0](../milestone0/evidence/native-verification.json)
