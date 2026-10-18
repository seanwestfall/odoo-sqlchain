# Browser acceptance evidence

Verified in the local Odoo development UI on 2026-09-14.

- Database: `chainsql_m0`, native PostgreSQL 16.15.
- Company: `YourCompany` (ID 1).
- Posted vendor bill: `BILL/2026/09/0002` (ID 57), vendor `Ready Mat`.
- Bill reference: `ChainSQL Milestone 1 demo`.
- Outstanding amount: USD 30.00; simulated amount: `30000000` atomic units, 6 decimals.
- Company-specific approved wallet: `Milestone 1 simulation wallet` (ID 1).
- Network/recipient: `mock:local` / `mock:ready-mat`.

The browser walkthrough opened Vendor Bills, opened this bill, selected its ChainSQL tab, clicked **Prepare test request**, **Approve test request**, **Queue test operation**, and **Refresh mock result**.

The final UI showed:

- Request revision: `1`.
- Fingerprint: `5a9b6ae96718a8709c0667390f0c5e370044d380081934be21df18c2ff18edb6`.
- Operation UUID: `294d4059-2be1-4b15-8121-4c2f8b1667b2`.
- Approval outcome: **Approved for simulation**; actor: Mitchell Admin.
- Policy: `mock-v1`.
- Status: **Simulated result observed**.
- Receipt: `mock:294d4059-2be1-4b15-8121-4c2f8b1667b2`.
- Review reason: **Simulation only; no blockchain transfer or accounting posting.**

[Open the operation](http://localhost:8070/odoo/vendor-bills/57/chainsql.operation/1).
[Open the bill](http://localhost:8070/odoo/vendor-bills/57).

The separate native-database acceptance suite verifies duplicate-click concurrency, rollback, company isolation, immutable fields, approval invalidation, and the actual worker process; see [integration.json](integration.json). No Circle API or real network transfer is involved in this milestone.
