# Milestone 4: x402 v2 resource purchase

Completed in the development instance on 2026-10-18. A real HTTP 402 challenge led to one **0.01 Base Sepolia test-USDC** payment and a synthetic vendor-verification response linked through Odoo's ORM to operation 1, bill 57 (`BILL/2026/09/0002`). The merchant is our demonstration endpoint, not an independent supplier or a real verification service.

## Evidence

- `evidence/live.json`: observed receipt, returned resource, exact-authorization replay, and Odoo linkage. Purchase UUID `13ea545c-3929-43de-ac5f-04547de22b36`, Odoo purchase record 6.
- Transaction: https://sepolia.basescan.org/tx/0x637aceb0e03362067e8d55f56d3823a56f17cae6b66017672d0d9b95b7559dd4
- `evidence/compatibility.json`: facilitator `/supported` response and funded balance before purchase.
- `evidence/native.json`: native PostgreSQL acceptance checks, including concurrent budget limits, persistence failure, fencing, revocation, lost response, and encrypted authorization access restrictions. Provider interactions in these tests are synthetic.
- `evidence/protocol-tests.txt`: 17 tests for SDK v2 challenge parsing, changed price/payee/domain/network, egress restrictions, and EIP-712 signature binding.
- `evidence/odoo-queue.json`: queue rollback, duplicate prevention, cross-company isolation, direct-write prevention, and material bill edit invalidation.

The live purchase initially settled and delivered before an RPC observation failure. Reconciliation recovered the original transaction. A subsequent authenticated HTTP replay returned the same transaction and resource, with the stored authorization digest unchanged. The bill remains `not_paid`, residual 30.00. No vendor payment or accounting journal entry is created by a resource purchase.

## Compatibility and units

| Component | Selected pilot path |
| --- | --- |
| Network | Base Sepolia, `eip155:84532` |
| Asset | USDC ERC-20 `0x036CbD53842c5426634e7929541eC2318f3dCF7e` |
| Units | Integer strings, 6 decimals; `10000` = 0.01 test USDC |
| Scheme | x402 v2 `exact`, EIP-3009 `TransferWithAuthorization` |
| Signing domain | name `USDC`, version `2`, chain ID 84532, exact token contract |
| Wallet | Existing Circle developer-controlled EVM test EOA; typed-data signing |
| Facilitator | `https://www.x402.org/facilitator`; `/supported`, `/verify`, `/settle` |
| Merchant | Loopback-only ChainSQL demo, GET `/vendor-verification/11?version=1` |
| Fees | Facilitator pays native ETH gas; payer fee allowance 0 |
| Receipt evidence | Successful canonical L2 receipt, matching Transfer and AuthorizationUsed events; at least two successor blocks |

The recorded receipt was **not L1-finalized** at observation. Its evidence says so explicitly. Arc vendor payments from milestone 3 are a separate path; this does not establish x402-on-Arc support. The captured facilitator capabilities did not advertise Arc. Token address reference: https://developers.circle.com/stablecoins/usdc-contract-addresses . Protocol reference: https://docs.x402.org/ . Runtime capability checks and the actual settlement, not generic EVM compatibility, establish this pilot combination.

## Repeatable local setup

Prerequisites: milestones 0–3's disposable native PostgreSQL and Odoo instance, Python venv `.local/milestone2/venv`, Node supporting `--env-file`, native PG16 PGXS, Docker, existing Circle test wallet configuration, and Base Sepolia test USDC. Commands run from the repository root. Private files are excluded from Git.

```sh
npm ci --ignore-scripts --prefix milestone0/wallet
npm ci --ignore-scripts --prefix chainsql/x402
.local/milestone2/venv/bin/python milestone4/scripts/install.py
.local/milestone2/venv/bin/python milestone4/scripts/configure.py
```

Install the Odoo addon in the existing development database. Stop the app first, run the upgrade, and restart even if installation needs repair:

```sh
docker compose -f milestone0/compose.yaml stop odoo
docker compose -f milestone0/compose.yaml run --rm -T odoo odoo -d chainsql_m0 --no-http --stop-after-init -i chainsql_resource_account --log-level=error
docker compose -f milestone0/compose.yaml up -d odoo
```

For subsequent addon changes use `-u chainsql_resource_account`. The extension upgrade is 0.3.0 → 0.4.0. Existing Arc and transfer addons accept the new extension version.

Start the demonstration merchant in a dedicated terminal (keep it running when retrieving resources):

```sh
CHAINSQL_MERCHANT_JOURNAL="$PWD/.local/milestone4/merchant" node --env-file=.local/circle_wallet/.env chainsql/x402/merchant.mjs
```

The environment file supplies `CIRCLE_API_KEY` (a `TEST_API_KEY:` value), `CIRCLE_ENTITY_SECRET`, `CIRCLE_SIGNING_WALLET_ID`, and `CIRCLE_RECIPIENT`. Never copy these into browser code, Odoo fields, or evidence. The merchant uses only the recipient; production should give each process only its required environment values.

On a **fresh disposable pilot**, an independent policy operator runs `prepare.py` to approve one exact resource request and set company/wallet budgets to 10000 atomic units. This explicitly unpauses the shared boundary. Review other queued work before using it. `queue_purchase.py` queues through Odoo and runs transactional/security assertions. Both retain existing pilot state and refuse to create another purchase over it.

```sh
.local/milestone2/venv/bin/python milestone4/scripts/prepare.py
.local/milestone2/venv/bin/python milestone4/scripts/queue_purchase.py
.local/milestone2/venv/bin/python milestone4/scripts/run.py PURCHASE_UUID
```

The existing completed pilot should **not** be recreated. To observe its original payment again:

```sh
.local/milestone2/venv/bin/python milestone4/scripts/run.py 13ea545c-3929-43de-ac5f-04547de22b36 --reconcile
```

Open http://localhost:8070/odoo/vendor-bills/57/chainsql.operation/1 and select **Refresh resource purchases**. Open purchase record 6 in the resource-expenses list to see the JSON response, receipt and request. Queueing is separate from execution: this pilot uses a trusted operator CLI, not a continuously running signer service.

`renew_unsigned.py` is a narrowly guarded recovery utility for an expired request with no authorization, dispatch, or reservation. It is not a payment retry mechanism. The initial unsigned request expired before execution and was cancelled; revision 2 is the completed purchase.

## Enforcement and recovery

- SQL policy role approves immutable payment snapshot plus exact request. The SHA-256 fingerprint covers both, including URL, method/body, version, operation, price, asset/domain, destination, validity, and approval identity. This fingerprint is the EIP-3009 nonce. The contract enforces nonce single-use, amount, destination and validity.
- `request_resource_v1` delegates to the restricted transfer command interface. Odoo never gets direct outbox or authorization writes. Queue and linked record share the bill transaction; a row lock serializes clicks. Company rules restrict purchase visibility, and bill/wallet invalidation triggers revoke stale authority.
- Existing SQL budget reservations, fenced claims, dispatch checks, and role separation remain in force. Atomic company and wallet limits apply before signing. The resource tenant is separate from the invoice-payment tenant.
- The restricted executor validates the actual challenge before signing and again before payment transmission. Only one literal loopback route family, GET and empty body are permitted. Redirects are rejected. Facilitator origin and RPC are fixed. Resource and facilitator response sizes and timeouts are bounded.
- Exact signed bytes are AES-GCM encrypted in the independent fsynced journal before SQL authorization persistence. Failed persistence cannot dispatch. Retries reuse these bytes. Only signer credentials can read ciphertext; public status and Odoo contain sanitized evidence.
- The merchant fsyncs an intent before settlement and caches settlement/resource results. The executor separately journals intent, ciphertext, receipt reference and delivered resource. Same-nonce replay cannot create another economic payment, and redelivery requires independently observed payment before bypassing an expired challenge window.
- A timeout or unavailable provider remains pending; reservations are retained. Reconciliation searches the original authorization's event or transaction. Failed resource delivery is distinct from payment status. A dispatched cancellation requires reconciliation/compensation; local expiry alone never releases its budget.
- Preserve `.local/milestone4/journal`, `.local/milestone4/merchant`, and the encryption key in separate protected backups alongside the database. Restore with execution paused. Reconcile original IDs first. Missing/mismatched independent journal state fails closed and requires operator review, rather than creating a new authorization. Resource tables are registered for extension dump/restore; no new full end-to-end disaster-recovery exercise is claimed here.

The restricted executor, DB policy administrator, host administrator, observer and Circle credentials are trusted. Budget limits are enforced by SQL plus this executor, **not by a general on-chain spending-limit contract**. A host owner or anyone possessing Circle credentials could bypass the application boundary. Do not give those credentials or host access to a delegated model. Production requires separate service identities/hosts and reviewed deployment controls. This is a testnet pilot with synthetic content; FX, resource-expense journal posting, third-party merchants and generalized egress are not implemented.

## Local verification (no live payments)

```sh
node --test chainsql/x402/protocol.test.mjs
.local/milestone2/venv/bin/python milestone4/scripts/verify_native.py
```

Native tests create a uniquely named disposable database and leave it available for inspection. `finalize.py` is the separate live acceptance script: it observes, replays the **existing** signed authorization, syncs Odoo via ORM, checks the unchanged bill, and writes `evidence/live.json`. It requires the merchant and network. It does not issue a new payment authorization.
