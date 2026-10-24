# Milestone 6: private document proofs and x402 seller

The local implementation is ready for demonstration. It uses explicitly synthetic Odoo data. **No new live x402 payment or Arc publication was performed for this milestone.** Paid delivery/recovery is exercised with a synthetic settlement ledger; SDK/EIP-712 validation uses real locally generated signatures. This is not evidence of independent supplier adoption or a production deployment.

## Open the demonstration

Odoo: http://localhost:8072/odoo/vendor-bills/70 (local development login `admin` / `admin`). Open **Document proofs**. Snapshot 1 is approved; its source attachment was deliberately edited afterward. **Verify source** reports a mismatch; the retained approved version remains unchanged. The separate M5 app on 8071 and the existing public preview were not switched.

The private seller listens only on `127.0.0.1:8096`. Its resource URL and bearer credential are in ignored `.local/milestone6/seller-sample.json`; the initial buyer grant expires after 24 hours. An unauthenticated visit returns 404 by design, even with a payment header. An authorized request returns an actual HTTP 402 with `PAYMENT-REQUIRED`. The operator must explicitly renew an expired grant, within the retained version's lifetime. Do not paste credentials into tickets or publish this directory.

## What is implemented

* `chainsql_document_account` snapshots exact attachment bytes with an immutable UUID, originating bill/company/attachment reference, source version, SHA-256 digest, salted commitment, approval identity and 30-day retention. Explicit approver actions create and approve snapshots. RPC create/write/delete are blocked; company rules and linked bill read access apply to private export and approval. Operators see metadata, not ciphertext/exported content.
* AES-256-GCM protects snapshot contents (including random 32-byte salt), with the version UUID as authenticated associated data. Private seller versions use the same format with their own key. Changed source attachments do not mutate approved snapshots. Approvals cover bytes, not the truth of their statements.
* A reusable authenticated HTTP route factory sells only a specifically granted immutable resource version. Token identity, buyer wallet, company/version grant, retention, price, recipient, network, EIP-712 domain and complete x402 resource descriptor are checked. Payment never creates an access grant. Management methods are local operator APIs, not HTTP endpoints.
* The seller uses x402 v2 `exact`/EIP-3009 on **Base Sepolia**, USDC `0x036CbD53842c5426634e7929541eC2318f3dCF7e`, six-decimal integer units. The sample price is `10000` atomic units (0.01 test USDC). This is separate from Arc invoice payments. The bridge queries facilitator capabilities, verifies the authorization, and independently observes the expected transfer/nonce and canonical receipt before delivering bytes.
* SQLite WAL with FULL synchronization durably records the exact encrypted authorization and request fingerprint before dispatch. An atomic state transition permits one settlement caller. A lost response leaves an uncertain attempt; retries observe the original authorization and do not settle again. Paid replay returns the originally purchased bytes and payment reference, subject to the current access grant and retention.

## Retention and access policy

Snapshots preserve purchased version access after ERP edits **until the earlier of grant expiration, revocation, or content retention expiration**. Revocation also denies a previously paid replay. Refunds/compensation are an operator workflow; the implementation does not silently create refunds or a new charge. An expired authorization is not newly dispatched. Uncertain purchases prevent seller content purge pending review.

Odoo's original attachment remains governed by Odoo's own filestore/access/backup policy; this addon neither encrypts nor deletes that original. The SQL scaffold can store bytes, and the addon stores encrypted bytes in PostgreSQL: neither is hash-only. Logical purge clears snapshot ciphertext, retaining audit metadata. It is not secure erasure of PostgreSQL/SQLite WAL, replicas, exports or backups. Deployment needs a coordinated retention policy covering these copies, encrypted volumes/backups, restricted operators, key escrow and restore drills. The demo's `.local` parent is mode 0700; seller credentials/keys/exports are mode 0600. The Odoo key mount is readable by the container's Odoo UID inside that protected directory. The seller has a separate key; losing either key loses the corresponding retained content.

The seller is a loopback pilot with bearer authentication and a single durable local journal. Production needs TLS, managed identity/token rotation, separately administered key custody, and a production journal/recovery design. Do not run separate seller replicas with independent journals. Restores must reconcile every dispatched authorization before accepting new settlement work; a pre-dispatch backup alone cannot establish that no payment occurred. Keep payment identifiers and journal backups under the same retention controls. A crash after the dispatch claim but before transmission sacrifices automatic progress: operator reconciliation is required, never a fresh payment merely to get unstuck.

## Repeatable setup and checks

From the standalone ChainSQL repository, with the M5 disposable database available:

```sh
npm ci --ignore-scripts --prefix chainsql/x402
npm ci --ignore-scripts --prefix milestone0/wallet
# Use a Python environment with cryptography installed (tested with the existing M2 venv).
CHAINSQL_RUNTIME_ROOT=/Users/sean/Projects/odoo python milestone6/scripts/setup_demo.py
# Captures private bytes: keep this output local and private.
umask 077
docker compose -f milestone6/compose.yaml exec -T odoo odoo shell -d chainsql_m6_dev --no-http --log-level=error < milestone6/scripts/odoo_acceptance.py > .local/milestone6/acceptance-output.txt
python milestone6/scripts/prepare_seller_demo.py
python milestone6/scripts/start_seller.py
python milestone6/scripts/check_demo.py
python milestone6/scripts/test_private_seller.py
node --test chainsql/x402/document_commitment.test.mjs chainsql/x402/seller_bridge.test.mjs
```

The setup clones the M5 database once and installs only into `chainsql_m6_dev`. Acceptance creates labeled sample records each run. The seller handoff refuses to replace an existing sample with a different version: retain its journal and use a new isolated directory for another run. `start_seller.py` installs a macOS user LaunchAgent `com.chainsql.m6.private-seller`, with no public listener. Stop it with `launchctl bootout gui/$(id -u)/com.chainsql.m6.private-seller`. No signing keys or payment requests are generated by setup/check scripts.

## Optional Arc commitment publication

`chainsql/x402/document_cli.mjs` implements an operator-only, externally signed transaction publisher and independent verifier. It is implemented and fixture-tested, **not live published**. It does not provide a new Circle signing integration or grant autonomous spending authority. Use a separately approved dedicated publishing wallet and its controlled signing path; do not concurrently use the invoice-payment wallet's nonce stream.

The commitment is:

```
SHA256(UTF8("ChainSQL/document-commitment/v1\0") || salt[32] || SHA256(original_bytes)[32])
```

Only the tagged 32-byte commitment is placed in transaction data, never plaintext, raw document digest or salt. The private original and manifest retain the salt. This supports a single-document commitment; no batch/Merkle inclusion proofs are claimed.

The signed transaction must be EIP-1559, Arc **testnet 5042002**, zero value, sender-to-self, exact approved nonce and tagged commitment, with maximum gas cost within the approved native USDC fee ceiling (18-decimal atomic units). Approval JSON fields are exactly `approval_id`, `approved_by`, `commitment`, `dedicated_wallet: true`, `fee_ceiling_atomic` (decimal string), `nonce` (decimal string), `policy_version: "document-publication-v1"`, `publisher`, and ISO `valid_until`. This local approval file is an operator assertion, not a cryptographic approval service: the external signer and filesystem/role separation must enforce who can authorize it. Never expose this CLI or approval files as agent tools.

```sh
node chainsql/x402/document_cli.mjs publish PRIVATE_APPROVAL.json PRIVATE_SIGNED_TX.txt PRIVATE_JOURNAL_DIRECTORY
node chainsql/x402/document_cli.mjs verify ORIGINAL_BYTES PRIVATE_MANIFEST.json
node chainsql/x402/document_cli.mjs verify ORIGINAL_BYTES PRIVATE_MANIFEST.json TX_HASH PUBLISHER_ADDRESS
```

Before broadcast, the publisher validates and fsyncs the exact signed transaction and approval in a publisher/nonce journal. Replays cannot substitute another transaction at that nonce. Timeouts reconcile the original hash; no new signature or nonce is generated. Independent verification fetches the transaction, successful receipt, canonical block and finalized block from Arc and checks sender, destination, zero value and exact commitment. A commitment proves correspondence to bytes, not business accuracy.

References: [x402 HTTP flow](https://docs.x402.org/core-concepts/client-server), [Arc network configuration](https://docs.arc.io/arc/references/connect-to-arc).

## Acceptance evidence

* `evidence/odoo-acceptance.json`: 15 checks against the installed Odoo addon, including immutable export, changed source, company isolation, restricted content and retention.
* `evidence/private-seller-tests.txt`: 25 tests, including actual local HTTP 402/delivery/replay with a **synthetic settlement provider**, durable restart recovery, single dispatch, revoked access and encrypted authorization storage.
* `evidence/node-tests.txt`: 19 real-signature/SDK and commitment tests; chain observations use fixtures.
* `evidence/demo-checks.json`: four checks against the running local seller and independent byte verifier. Explicitly records no live payment/publication.

A fresh live seller payment and optional live Arc publication remain separate integration acceptance steps. The existing M4 transfer must not be represented as an M6 seller payment. No production-readiness or independent supplier participation is claimed.
