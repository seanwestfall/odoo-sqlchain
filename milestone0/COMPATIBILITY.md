# Milestone 0 compatibility report

Evidence observed September 14, 2026 UTC. **Milestone 0 is not yet complete:** no
Circle wallet was configured, and no live test transfer occurred. The user has a
Circle Console account; the saved credential is currently a `TEST_CLIENT_KEY`,
not the server `TEST_API_KEY` required for developer-controlled wallets.
All local database acceptance checks and the written x402 capability/blocker check
are complete. The earlier shared-chat ZIP was not available as a local artifact;
the user confirmed no extension had been started. This is a new, minimal baseline.

| Acceptance item | Result | Evidence |
|---|---|---|
| Revision, packages, paths, repeatable startup | Verified | [Setup](README.md), [baseline](evidence/baseline.json), [runtime](evidence/odoo-runtime.json) |
| Disposable accounting-only Odoo | Verified | `chainsql_m0`; `account` installed, `purchase`, `stock`, `mrp` uninstalled |
| Native SQL extension and distinct roles | Verified | PostgreSQL 16.15; ChainSQL 0.1.0 owned by `chainsql_owner` |
| Backup/restore of extension runtime data | Verified | [18 native checks](evidence/native-verification.json); exact row comparison after actual restore |
| Arc identity/interface and Circle path selection | Documented + read-only RPC verified | [Network probes](evidence/network-probe.json), pinned SDK and transfer harness |
| Small Circle transfer and observed receipt | **Blocked** | Replace frontend test client key with a test server API key; automated entity-secret/wallet setup is ready; funding and live receipt still pending |
| x402 v2 capability matrix / blocker | Complete as blocker evidence | Selected facilitator advertises Base Sepolia exact/v2, not Arc; merchant not yet selected |

## Arc interface decision

| Field | Selected value |
|---|---|
| Chain | Arc Testnet, `eip155:5042002` |
| Observed `eth_chainId` | `0x4cef52` = `5042002` |
| RPC | `https://rpc.testnet.arc.network` |
| Wallet/signing service | Circle developer-controlled EOA, `ARC-TESTNET` |
| Transfer interface | USDC ERC-20 `0x3600000000000000000000000000000000000000` |
| Function | `transfer(address,uint256)` through Circle contract execution |
| Payment units | Integer strings, **6 decimals**; 0.01 USDC = `10000` |
| Native transaction `value` | `0` for this token call |
| Native gas/balance units | Integer strings, **18 decimals** |
| Test fee ceiling | `50000000000000000` native units = 0.05 USDC |

Arc's native and ERC-20 balances represent the same USDC holding. ERC-20 reads
truncate twelve native decimal places; do not add the two balances or round away
gas precision. Chain quantities use `BigInt`, serialized as decimal strings.
The observed `decimals()` result is 6. [Arc stablecoin model](https://docs.arc.io/arc/concepts/stablecoin-native-model),
[contract addresses](https://docs.arc.io/arc/references/contract-addresses).

Circle documents Arc EOA wallets and contract execution. The chosen SDK handles
Circle's entity-secret encryption; PostgreSQL never receives that secret. The
path is documented, **not yet operationally validated with this user's wallet**.
[Wallet quickstart](https://developers.circle.com/wallets/dev-controlled/create-your-first-wallet),
[contract execution API](https://developers.circle.com/api-reference/wallets/developer-controlled-wallets/create-developer-transaction-contract-execution).

### Fees and receipt interpretation

Estimate gas for the exact calldata; add a 20% gas-unit margin and cap the total
maximum fee before submission. The actual fee is `gasUsed * effectiveGasPrice`
in 18-decimal native units. Circle's custom `maxFee`/`priorityFee` API fields are
Gwei strings, so the adapter explicitly converts from native atomic units by
`10^9`. Fee levels alone would not establish the probe's maximum gas budget.
[Arc fees](https://docs.arc.io/arc/references/gas-and-fees),
[Circle fee field definitions](https://developers.circle.com/api-reference/wallets/developer-controlled-wallets/create-developer-transaction-contract-execution).

Wait for Circle `COMPLETE`, then independently verify the RPC transaction, receipt
success, receipt/block hashes, finalized block height, and the exact token Transfer.
Circle's accepted transaction ID alone is not settlement. The observer matches
the USDC contract emitter; it does not count the 18-decimal system emitter as
another payment. Gas deductions are accounted from receipt gas fields.
[Circle transfer lifecycle](https://developers.circle.com/wallets/dev-controlled/transfer-tokens-across-wallets),
[Arc system events](https://docs.arc.io/arc/references/usdc-system-events).

Documentation caveat found during review: Arc's wallet example used hex
`0x4CF4B2` alongside decimal `5042002`, while RPC returns `0x4cef52`; the latter is
the actual hex conversion of `5042002`. A gas-page native-send example used six
decimals despite its 18-decimal native-unit table. This harness uses observed chain
identity and explicit interface units, not those conflicting examples.
[Wallet integration example](https://docs.arc.io/integrate/wallets),
[gas example](https://docs.arc.io/arc/references/gas-and-fees).

## x402 capability matrix

Selected facilitator: **https://x402.org/facilitator**. Queried its actual
`GET /supported` endpoint; the complete timestamped response and RPC requests are
in [network-probe.json](evidence/network-probe.json). A wildcard signer entry
`eip155:*` does not replace an explicit entry in `kinds`.

| Combination | Asset / method | Merchant | Live capability result | Conclusion |
|---|---|---|---|---|
| x402 v2 / `exact` / Arc `eip155:5042002` / selected facilitator | Arc USDC ERC-20; proposed EIP-3009 | None selected | No Arc entry in `kinds` | **Blocked for this facilitator; no x402-on-Arc claim** |
| x402 v2 / `exact` / Base Sepolia `eip155:84532` / selected facilitator | USDC `0x036CbD53842c5426634e7929541eC2318f3dCF7e`; EIP-3009 candidate | None selected | `exact`, v2, network explicitly advertised; token reads succeed | Declared fallback test-network candidate; merchant challenge and settlement remain untested |
| Direct Arc payment / Circle | Arc USDC ERC-20 `transfer`; no x402 | User-controlled test recipient | Wallet path documented; RPC identity/decimals verified | Awaiting sandbox setup and observed test transfer |

The x402 EVM specification provides EIP-3009, Permit2, and delegated-account
methods. They require their own deployment, asset, and facilitator compatibility;
switching methods is not evidence of support. Base Sepolia's USDC address is
confirmed in Circle's address reference. [x402 exact EVM spec](https://github.com/x402-foundation/x402/blob/main/specs/schemes/exact/scheme_exact_evm.md),
[Circle USDC addresses](https://developers.circle.com/stablecoins/usdc-contract-addresses),
[x402 network support](https://docs.x402.org/core-concepts/network-and-token-support).

### EIP-3009 finding

Arc's token answered `authorizationState(address,bytes32)` and `DOMAIN_SEPARATOR()`
in read-only calls; Base Sepolia's USDC answered both as well. This is positive
interface evidence, **not a successful signed authorization or facilitator
settlement test**. No domain name/version is assumed or copied from Ethereum.
The selected facilitator's missing Arc capability independently blocks that
combination even if token-level authorization support is later proven.

Before a future x402 purchase, select an actual merchant route and recipient,
inspect its v2 `PAYMENT-REQUIRED`, and bind the approved scheme, chain, asset,
integer amount, payee, deadline and signing domain. Then test facilitator verify,
settle, on-chain receipt and resource delivery. The `/supported` response does
not enumerate a blanket token or merchant allowlist and is insufficient alone.
[x402 v2 specification](https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md).

No merchant was fabricated, no authorization signed, and no `/settle` call made.
Using Arc for vendor transfers and Base Sepolia for x402 would demonstrate **two
distinct network paths**, not x402 settlement on Arc. The current code leaves
x402 purchasing disabled. This is the explicit blocker outcome permitted by the
milestone's x402 acceptance criterion.

## What remains to close the milestone

Complete the Circle setup in [README.md](README.md#complete-the-circle-evidence),
run the bounded test transfer, and retain the resulting `arc-transfer.json`.
Only after its actual receipt passes verification should this report's transfer
row and overall milestone status change to complete. Offline receipt tests use
synthetic fixtures and must never be presented as live-transfer evidence.

Circle already documents the needed API: an entity secret is a developer-generated
32-byte value registered in encrypted form, not a credential issued alongside the
API key. `wallet/setup.mjs` automates registration and two test wallets, and refuses
a frontend client key before network calls. In Console, choose **API & Client Keys
→ Create a key → API Key**, in test mode. Restricted access with **Wallets:
Read/Write** is the relevant product permission.
[Key creation](https://developers.circle.com/contracts/create-api-key),
[secret registration](https://developers.circle.com/wallets/dev-controlled/register-entity-secret).
