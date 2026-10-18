# Odoo → worker → restricted signer → simulator → observer

Completed on 2026-09-15 in the disposable native `chainsql_m0` database.

The browser opened [BILL/2026/09/0002](http://localhost:8070/odoo/vendor-bills/57/chainsql.operation/1), selected **Transfer boundary**, and clicked **Request bounded test transfer**. Odoo displayed the immutable snapshot and state `requested`.

The separate `transfer-worker` container then claimed this UUID and called the private boundary service. It returned:

```json
{"state":"observed","receipt":"mock-transfer:686613e7-dab0-460c-bcd4-31d93a7537d9"}
```

Clicking **Refresh transfer status** in Odoo displayed:

- Transfer: `686613e7-dab0-460c-bcd4-31d93a7537d9`.
- State: `observed`.
- Reservation: `false` (converted to observed spend).
- Tenant: `odoo:chainsql_m0:1`; business reference: `account.move:57`; revision: `1`.
- Source wallet: `pilot-company-wallet`; recipient: `mock:ready-mat`.
- Network/interface: `mock:local` / `mock-usdc-6`.
- Value: `30000000` atomic units; fee ceiling: `10000`; observed fee: `1`.
- Policy version: `boundary-v1`; independent approval identity: `mock-only-acceptance-harness`.
- Receipt: `mock-transfer:686613e7-dab0-460c-bcd4-31d93a7537d9`.
- Preparation identity: `transfer-v1:686613e7-dab0-460c-bcd4-31d93a7537d9`.

The cancel button was no longer offered after observation. No signing bytes were displayed. This is simulator evidence, not a Circle/Arc transfer or Odoo accounting payment.
