# Milestone 3 — Arc testnet payment loop

Status: **Milestone 3 complete for the single-asset Arc testnet pilot.** On 2026-09-16 UTC, approved bill **BILL/2026/09/0003** produced one finalized **0.01 test USDC** transfer and linked Odoo payment **1**. The acceptance harness discarded the submission response, recovered the original transaction through a fresh controller, and verified replay returned the same receipt without another broadcast. Odoo remained **In Payment**, pending clearing review. Arc execution was disabled after acceptance.

Live transaction: [0x7adc94c6…ab1559](https://testnet.arcscan.app/tx/0x7adc94c6ab6c12530d0f77a34176abe3856785bc3831583b682e8122aaab1559). Full evidence: `evidence/live.json`. Gas was `1552698000000000` native atomic units (18 decimals), or **0.001552698 test USDC**. It rounds to zero USD cents under the documented per-transaction policy, so no zero-valued fee journal entry was created; the exact fee and sub-cent audit remainder are retained.

## Circle setup and the 401

`GET /v1/w3s/config/entity/publicKey` authenticates the server API key. A 401 there precedes entity-secret encryption; generating another secret will not fix it. Circle supplies an API key; **you generate and register the entity secret**. The existing `.local/circle_wallet/.env` has a correctly shaped 32-byte hexadecimal secret. Its randomness/provenance cannot be established merely from its format. It is preserved, never printed or rotated.

The initial 401 has been resolved. For future installations, replace only `CIRCLE_API_KEY` in `.local/circle_wallet/.env` with the test **server API key** from Circle Console's API Keys section (`TEST_API_KEY:…`, not `TEST_CLIENT_KEY:…`). Keep credentials out of chat. Then, from the project root:

```sh
python3 .local/circle_wallet/create.py
```

The original Python script is retained beside it as `create.original.py`. The wrapper runs the pinned Node SDK setup helper at `chainsql/arc/setup.mjs`. It checks authentication before registration, keeps recovery material private, journals wallet creation idempotency keys before sending, and creates two **EVM-TESTNET EOA signing wallets**. This is Circle's documented sign-only path for an Arc transaction. Native `ARC-TESTNET` wallet creation is a different managed path and is not silently substituted here. An unresolved registration outcome stops for operator inspection; it does not rotate the secret or repeat registration blindly.

The helper adds `CIRCLE_SIGNING_WALLET_ID` and `CIRCLE_RECIPIENT` to `.env` and displays public funding addresses. Fund the source with **Arc testnet** USDC from the faucet; the pilot payment is 0.01 test USDC, with a 0.05 test USDC maximum gas allowance. Use a dedicated wallet with no other nonce-using clients. Test funds have no accounting value outside this demonstration.

Sources checked 2026-09-15:
- [Circle key types](https://developers.circle.com/api-reference/keys)
- [Generate and register the entity secret](https://developers.circle.com/wallets/dev-controlled/register-entity-secret)
- [Circle EVM-TESTNET signing flow](https://developers.circle.com/wallets/sign-transactions)
- [Sign transaction API](https://developers.circle.com/api-reference/wallets/developer-controlled-wallets/sign-transaction)
- [Arc integration and precision](https://docs.arc.io/integrate/infrastructure)
- [Arc finality and finalized tag](https://docs.arc.io/integrate/infrastructure/bridges)

## Repeatable local setup

Prerequisites are the Milestone 0 native PostgreSQL instance and Milestone 2 roles, Python environment and pinned SDK dependencies. Preserve their private configuration; do not recreate keys during recovery.

```sh
python3 milestone3/scripts/install.py
python3 milestone3/scripts/configure.py
docker compose -f milestone0/compose.yaml -f milestone2/compose.yaml stop odoo
docker compose -f milestone0/compose.yaml -f milestone2/compose.yaml run --rm -T odoo odoo -d chainsql_m0 --no-http --stop-after-init -i chainsql_arc_account --log-level=warn
docker compose -f milestone0/compose.yaml -f milestone2/compose.yaml up -d odoo
```

The extension upgrades to 0.3.0. Arc is independently disabled on initial installation. `configure.py` creates private `.local/milestone3/boundary.json` and worker configuration; it does not enable spending. The native boundary is intentionally separate from the existing mock boundary:

```sh
.local/milestone2/venv/bin/python chainsql/arc/service.py --config .local/milestone3/boundary.json
```

It binds to loopback port 8092. The delegated worker has only its database credential and calls this service with operation ID, claim token, and fence. Never give a worker the boundary configuration, Circle credentials, encryption key, or independent journal. Host OS administrators remain outside the pilot's restricted-worker threat model. Production requires an isolated service identity/host and protected key storage.

## Execution and accounting workflow

1. Create/post a **0.01 USD development vendor bill**, select a company-specific approved Arc recipient wallet, then prepare and approve its ChainSQL request. Use only the disposable `chainsql_m0` company books.
2. An independent SQL policy operator reviews the exact 14-field snapshot and installs company/wallet budgets and wallet permission through the existing restricted `set_budget_v1`, `set_wallet_v1`, and `approve_transfer_v1` commands. Tenant is `odoo:chainsql_m0:1:arc`; business reference is `account.move:<bill-id>`. Use `interface=arc-erc20-6-fee18`, `network=eip155:5042002`, `asset=USDC`, `policy_version=boundary-v1`, source Circle signing-wallet ID, amount `10000`, fee ceiling `50000000000000000`, and explicit UTC validity dates. Odoo must not have `chainsql_policy` membership. The ordinary worker cannot edit any of these controls.
3. The policy operator enables Arc with `enable_arc_v1(true)` and unpauses the general boundary only after wallet configuration, funding, and the snapshot/budgets are approved. Budget units are bound per tenant; mock fee units cannot share the Arc budget namespace.
4. In the operation's Transfer boundary tab, request the bounded test transfer. SQL enqueue and the Odoo operation link share one transaction. The worker can only claim the committed row:

```sh
.local/milestone2/venv/bin/python chainsql/boundary/worker.py TRANSFER_UUID --config .local/milestone3/worker.json --boundary-url http://127.0.0.1:8092
```

5. If a response is lost or the provider is unavailable, reconcile the **same** operation; do not make another bill revision or payment:

```sh
.local/milestone2/venv/bin/python chainsql/boundary/worker.py TRANSFER_UUID --config .local/milestone3/worker.json --boundary-url http://127.0.0.1:8092 --reconcile
```

6. Refresh the Odoo transfer status. Confirmed/reverted status, original transaction hash, chain/asset, amount, fee, receipt block/hash, finalized block/hash, provider request ID and observation timestamp are displayed in the sanitized status. This refresh performs **no accounting writes**.
7. Configure **Arc demonstration journals** as an accounting manager: USD company, bank journal, manual outbound method, reconcilable current-asset outstanding-payment account (not a cash/bank account), general gas journal, separate gas expense and current-asset clearing accounts. The explicit **Record and reconcile demonstration payment** action creates/posts `account.payment` with the ORM and reconciles the exact bill's payable lines. It rechecks the bill, recipient approval, full residual, currency, and configuration. It leaves the bill **In Payment**, with outstanding clearing awaiting normal accounting review. It does not call `action_validate()` or force Paid.

Only full USD bills are supported. Mapping is **1 test USDC = 1 demonstration USD**, not a claim about real cash or FX. Payment amount uses ERC-20 units (6 decimals); gas is native USDC (18 decimals) and posted separately. Gas rounds half-up to cents per transaction; the exact atomic gas amount and signed sub-cent rounding remainder remain recorded. A rounded zero fee creates no zero-valued journal entry. FX, partial payments, discounts, and changed obligations require manual review with defined rules. A reverted transaction records gas spend but cannot create a vendor payment through this action.

## Adapter and enforced boundary

- `prepare`: verifies chain/token precision, EVM-TESTNET EOA wallet, recipient, available balance and fee ceiling. SQL reserves value/fee atomically, allocates one sender nonce across workers, and fixes transaction fields and provider request UUID before signing.
- `sign`: Circle returns signed bytes; local decoding verifies chain, nonce, sender, token contract, transfer calldata, zero native value and fee limits. The provider's request UUID is a correlation ID, **not a Circle idempotency guarantee**. Economic replay protection is the fixed EOA sender/nonce and byte-for-byte persisted authorization.
- Authorization bytes are AES-GCM encrypted in the restricted SQL table **and** a private, fsynced independent journal keyed by tenant/business obligation. Ordinary SQL views, Odoo and worker responses never contain them. A failed save prevents transmission. Fenced claims prevent stale workers from saving or dispatching a new attempt.
- `submit`: rechecks current policy, revocations, wallet permission and pause switches, commits dispatch intent, looks up the original hash, then broadcasts only the saved bytes. A timeout/rejection is uncertain because a previous submission could already have settled. No replacement nonce or new payment is generated.
- `observe/reconcile`: verifies the receipt's transaction/block hash, exact Transfer event, gas cost and canonical finalized block. Arc documents deterministic BFT finality and maps `finalized` to latest committed block. Evidence here trusts the selected RPC; this is not an independently verified validator certificate.
- Observed success consumes reserved value and actual fees. Revert consumes gas only. Pending/unavailable/uncertain operations retain reservations. EVM transactions have **no protocol expiry**: the snapshot validity window restricts signing/dispatch, but expiry cannot release an existing signed authorization. Cancellation after signing requires reconciliation; after success it requires compensation, not an undo.
- Arc is blocked from the mock settlement/expiry-release path. Do not send Arc operations to the port-8091 mock service.

## Backup recovery

Stop workers/boundary first. Preinstall extension **0.3.0** and its grants into the empty restore target before loading the dump; PostgreSQL's extension CREATE uses the package default, not the dumped upgrade state. Exclude the already-created `SCHEMA chainsql` TOC entry exactly as `verify_native.py` does. Restore with errors treated as failures.

Before starting execution, set the general pause switch and disable Arc through the policy role. Preserve/recover the encryption key and **independent dispatch journal separately from the SQL backup**. Point the private configuration at the restored database and run:

```sh
.local/milestone2/venv/bin/python chainsql/arc/service.py --config .local/milestone3/boundary.json --recover
```

Recovery only observes original hashes; it never signs or broadcasts. A previously dispatched attempt may have settled after the backup. Saved authorization/plan plus a matching finalized receipt can be reconciled even if the restored dispatch state predates transmission. Missing database rows, missing authorizations/plans, unmatched independent-journal obligations, or absent receipts stop recovery for operator repair. They do not permit a new nonce. Re-enable execution only after every independent attempt is resolved. A reserved nonce abandoned before transmission can leave a nonce gap; the pilot deliberately stops for operator reconciliation instead of automatically recycling it.

## Verification and completion evidence

```sh
node --test chainsql/arc/adapter.test.mjs
.local/milestone2/venv/bin/python milestone3/scripts/verify_native.py
.local/milestone2/venv/bin/python milestone3/scripts/verify_odoo.py
node milestone3/scripts/probe.mjs
```

`evidence/native.json`: 31 passing native state-machine, role, concurrency, persistence-failure and backup/recovery checks. `evidence/odoo.json`: 12 passing ORM checks including explicit accounting, stale recipients, duplicate action, fee separation and In Payment state. The Node adapter has 13 offline tests including real local transaction signing/decoding with a public fixture key; provider responses are fixtures. `evidence/network.json` is a live **read-only** RPC probe.

Live evidence is now recorded in `evidence/live.json`: actual finalized Arc receipt, one linked Odoo payment, replay of the original hash, recovery after intentionally discarding the submission response, and the unchanged bill state before the explicit accounting action. The 56 local checks and read-only probe remain separately identified; synthetic receipts were not substituted for live completion.

## Completed acceptance and operation

- Odoo operation **2**, bill **58 / BILL/2026/09/0003**, linked payment **1**.
- Source: `0x9cea12375b83386a7366a50ba5626f1a4094efde`. Recipient: `0x176c176a4a14a89741337a438ddead22a4f6fd05`.
- Transfer **7a479e94-267e-4546-bc55-dc068a921d87**, finalized block **62331434**, ERC-20 value **10000** atomic units (0.01 USDC).
- The server key and existing registered secret were verified; two signing wallets were created. The user funded the source with 40 test USDC after the faucet API returned 403.
- Registration was initially ambiguous; `recover-setup.mjs` recovered the original idempotent wallet-set request without registering or rotating the secret. No recovery file was found in the local recovery directory; retain the original secret and any recovery file saved through Circle Console.
- The trusted `live_acceptance.py` harness installed a policy capped at one 0.01-USDC payment plus 0.05-USDC gas, queued the approved bill through Odoo, dispatched the persisted transaction, intentionally discarded its response, recovered via a fresh controller, verified replay, and performed the explicit ORM accounting action twice to check idempotency. It disabled Arc afterward.
- Do not rerun bill preparation or initiate another payment for this bill. Use the boundary reconciliation command or Odoo Refresh transfer status to inspect the existing receipt. The bill's remaining task is ordinary clearing review; chain confirmation alone did not force Paid.
