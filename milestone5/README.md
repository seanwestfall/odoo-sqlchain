# Milestone 5 — purchasing evidence and decisions

The sample implementation runs in **`chainsql_m5_dev` at http://localhost:8071**. The milestone 0–4 instance on port 8070 is unchanged. Purchase and Inventory (`purchase_stock`) and `chainsql_purchase_account` are installed in the sample clone. All execution acceptance tests use the mock queue: no Circle signing or chain payment occurs.

## What is implemented

The adapter gathers allowlisted evidence through Odoo's ORM as the requesting user: posted bill identity and amount, linked purchase lines, quantities ordered/billed/received, receipt move state, unit/subtotal consistency, tax and currency compatibility, normalized duplicate references, approval freshness, due/discount dates, and available delegated queue allowance. Other-company access is denied. The optional `should_be_paid` indicator is included only if installed. This Community revision's dedicated `account_3way_match` is an upgrade module, so the pilot uses source PO/receipt facts directly instead of claiming that optional feature is installed.

The deterministic baseline produces `pay_now`, `defer` with a date, `request_information`, or `hold`, with reason codes. Structured agent proposals are recorded separately from the baseline. Each immutable decision stores input references and their fingerprint, model/version label, proposing user, action, justification, policy version/revision and policy outcome. Human assessments retain the human identity and choice for comparison. Sample human choices in the tests are fixtures, not validation by an actual business.

Only a ChainSQL approver can configure a company's delegation policy. An eligible low-value action can queue without an additional human decision after the original operation is approved. Above-threshold or disabled-delegation cases require a human choice. Duplicate, missing receipt, amount inconsistency, stale approval, unavailable allowance or unsupported accounting evidence cannot be overridden into payment by an agent or a human threshold approval. Invoice payments still need the independent SQL payment approval and signer budget checks from milestones 2–3.

The company allowance is a **cumulative queue allowance**, not a bank balance or the signer's available on-chain funds. Both the per-operation limit and cumulative allowance are expressed as integer USD/USDC atomic strings (six decimals). Queue execution locks the policy, regathers evidence, checks its fingerprint and consumes allowance in the same transaction. Another decision cannot create a second obligation for the same operation. Allowance is conservatively retained once queued; automatic release on cancellation is not implemented.

Discount dates change the recommendation to amount review rather than silently altering an approved amount. FX, partial payments, services without receipt evidence, unlinked invoice lines and different purchase/bill units are outside the automatically payable pilot. Deferral is an advisory date, not a scheduled payment. Requests for information do not send messages automatically.

## Agent interface and untrusted documents

Use an authenticated Odoo user with the dedicated **Purchasing advisory agent (read only evidence)** group. It grants read-only Accounting, PO and receipt access plus controlled recommendation actions. Do not add normal Purchase/Inventory write roles; Odoo ACL grants are additive. A separate authorized executor/operator runs eligible actions; the advisory identity cannot edit bills, receipts or purchasing evidence. Do not grant the agent ChainSQL approver, system administrator, SQL policy, signer or observer credentials.

The controlled methods, callable through Odoo's authenticated model RPC, are:

```python
# records is a chainsql.operation recordset under the agent's own Odoo user/context.
evidence = records.action_purchase_evidence()
# Supply only the returned allowlisted JSON to the model, with a fixed instruction
# to choose one of the four actions. No document content or payment tools are needed.
result = records.action_recommend_purchase(
    {'action': 'hold', 'date': None,
     'justification': 'A duplicate reference requires a human review.'},
    model_version='your-provider/your-pinned-model-version',
)
```

Only the three proposal fields shown are accepted. `defer` requires a future ISO date; all other actions require `date=None`. Recipient, amount, asset, network, tools and limit fields are rejected. The model label is caller-supplied provenance, not a verified provider attestation; `created_by` records who supplied it. The default UI action uses `deterministic-planner-v1` and needs no external API or API credits. The adapter supports external agent proposals; this milestone does not install an unattended hosted LLM service.

Invoice narration, line descriptions, references as raw text, and attachment bytes are **not forwarded**. Duplicate normalization happens inside the authorized ORM adapter. A malicious attachment therefore cannot become system instructions. Justifications are rendered as Odoo text and are never executed. Structured malicious proposals are tested independently. Native payment destinations continue to come exclusively from immutable, separately approved payment snapshots.

Receipt, purchase, policy and material bill changes invalidate independent SQL authority in the same transaction through restricted invalidation commands. Evidence collection never uses privileged table reads; `sudo` is confined to internal invalidation, which returns no data. Direct administrator SQL changes to purchase/stock tables are outside this ORM adapter's enforcement boundary. The existing extension retains its own approval, reservation and dispatch controls.

## Browse the sample

Open http://localhost:8071 (the cloned demo uses the existing development login). Select **ChainSQL Decisions → Decisions** to compare proposed actions, baseline reasons, human choices and outcomes. The latest generated IDs are in `evidence/integration.json`; open that bill's ChainSQL operation to see its decision history. The **Evaluate purchasing evidence** button creates a new immutable snapshot. **Execute eligible decision** rechecks it before queueing. Old decisions stay as historical evidence, not current authority.

The malicious sample attachment was created by the disposable test runner. Its contents are excluded from the agent input; the new app uses an isolated filestore and does not migrate the original database's attachments.

## Setup and tests

Prerequisites: completed milestone-4 development database, initialized Odoo submodule, native PostgreSQL, and Docker. The setup script clones the existing *disposable* database, briefly stopping and restoring its Compose services only when a clone is needed. It reuses local DB credentials in an ignored configuration file and creates an isolated app/filestore. Do not point it at real company books.

On this workstation the original runtime remains in the previous checkout:

```sh
cd /Users/sean/Projects/chainsql
CHAINSQL_RUNTIME_ROOT=/Users/sean/Projects/odoo python3 milestone5/scripts/setup_demo.py
python3 milestone5/scripts/test_decisions.py
CHAINSQL_RUNTIME_ROOT=/Users/sean/Projects/odoo python3 milestone5/scripts/run_checks.py
```

For a fresh standalone environment set `CHAINSQL_RUNTIME_ROOT` to that environment's project root. The PostgreSQL binary location can be changed through `PG_BIN`. Integration tests assert the database name, create clearly named `M5 SAMPLE` fixtures, and queue only `mock:local` operations. The database is retained for inspection. `evidence/integration.json` records integration checks and the observed mock result; `evidence/unit-tests.txt` records 15 deterministic tests. `evidence/revocation.json` additionally verifies that a real purchase edit revokes independent SQL authority before any transfer is requested. Do not run a live-network worker against this clone or treat copied old approvals as new authorization.

## Completion boundaries

Sample evidence demonstrates a real PO → posted bill → receipt workflow; duplicate and missing-receipt detection; recommendation changes; threshold and budget controls; structured proposal restrictions; cross-company denial; and one mock obligation with the bill still unpaid. A real business has not supplied cases yet, as confirmed by the user. Business validation and comparison against genuine human decisions remain outstanding. These fixtures do not establish production accounting accuracy or general prompt-injection immunity beyond the explicit input/authority boundary tested here.

To complete committed mock jobs and synchronize the result (requires the milestone-2 Python dependencies):

```sh
CHAINSQL_RUNTIME_ROOT=/Users/sean/Projects/odoo /Users/sean/Projects/odoo/.local/milestone2/venv/bin/python milestone5/scripts/observe_mock.py
```
