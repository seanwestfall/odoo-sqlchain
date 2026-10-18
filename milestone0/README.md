# Milestone 0 — reproducible compatibility baseline

Status: **database baseline verified; overall milestone remains blocked on a live Circle sandbox transfer.**
See [compatibility report](COMPATIBILITY.md) for network choices, evidence, and remaining gates.

This is a disposable, accounting-only instance at **http://localhost:8070/odoo/vendor-bills**
(login `admin`, password `admin`). Native PostgreSQL runs on `127.0.0.1:55432`.
The original Manufacturing demo at port 8069 is separate. No real company books
were copied. Only `account` and its dependencies/demo data are installed here.

## Architecture and scope

The reusable core lives in `chainsql/extension`, outside Odoo's addons. It is an
actual PostgreSQL SQL/PLpgSQL extension installed using PGXS and `CREATE EXTENSION`.
It deliberately implements only nonfinancial probe operations for this milestone.
The user-supplied HTTP C example was reviewed as a starting reference; it is not
compiled or installed. HTTP, wallet secrets and signing stay outside PostgreSQL.

The future separate ChainSQL dashboard should call an authenticated ChainSQL
service. ERP adapters supply business authorization/context and queue committed
requests. Odoo accounting changes must use Odoo's ORM/API; a worker's blockchain
receipt does not itself mark a bill paid. The worker has no access to Odoo tables.
No Odoo core edits, dashboard, payment queue, receipt matching, spending policy
engine, or production recovery worker are claimed by this milestone.

## Exact baseline

- Odoo Community 19.0: `7bbce824a1897a912441a7f0511ffec505cbe1d5`.
- PostgreSQL: native Homebrew **16.15**, Apple Silicon macOS; not a Docker database.
- Odoo Python runtime: **3.12.3**, in the pinned `odoo:19.0` Docker image.
- Image digest: `sha256:a627eda6b4154eead21c4fca55f84f1671d870ca111aa57f93ca305861bc4613`.
- ChainSQL extension: **0.1.0** (new baseline, not the inaccessible earlier ZIP).
- Configured addons: checkout `addons` mounted at `/mnt/extra-addons`; built-in
  addons come from checkout `odoo/addons` under `/usr/lib/python3/dist-packages/odoo`.
- Full observed packages: [Python](evidence/odoo-python-freeze.txt),
  [system](evidence/odoo-system-packages.txt). Source hashes: [baseline.json](evidence/baseline.json).
- Wallet harness: Node 24.19.0 used; Node 22+ required. Circle SDK 10.8.0, viem 2.56.5;
  transitive versions are pinned by `wallet/package-lock.json`.

## Fresh setup

Run from the repository root containing these milestone files. Docker Desktop
must be running. `PG_BIN` can override the native PostgreSQL executable directory.

```sh
brew install postgresql@16
python3 milestone0/scripts/native_setup.py
make -C chainsql/extension PG_CONFIG=/opt/homebrew/opt/postgresql@16/bin/pg_config install
/opt/homebrew/opt/postgresql@16/bin/psql -X -h "$PWD/.local/milestone0/socket" -p 55432 -U m0_admin -d chainsql_m0 -f milestone0/scripts/install_extension.sql
docker compose -f milestone0/compose.yaml run --rm odoo odoo -i account --with-demo --stop-after-init --no-http --log-level=warn
docker compose -f milestone0/compose.yaml up -d
npm --prefix milestone0/wallet ci --ignore-scripts
```

If Homebrew reports links conflicting with existing `libpq` binaries, verify
`/opt/homebrew/opt/postgresql@16/bin/postgres --version`; the installed versioned
binaries are sufficient. Do not overwrite existing tool links. `make install`
writes two files to that PostgreSQL installation's extension directory and may
need filesystem permission. Do not run initialization against existing business
databases. On repeat starts, skip `-i account`.

`native_setup.py` is repeatable, generates local random database credentials,
and grants no superuser/role-creation/database-creation privileges to application
or worker roles. It uses a private Unix socket for the local administrator and
SCRAM authentication for TCP. The socket directory is under an owner-only folder.
The host's OS user/DB administrator remains trusted. This is local process
separation, not isolation against the machine owner.

`chainsql_owner` is NOLOGIN and owns the extension and its objects. `chainsql_odoo`
owns Odoo's database and tables but receives only enqueue/status access to
ChainSQL. `chainsql_worker` receives only claim/complete access. Neither login role
belongs to the extension owner role; neither can directly read/write the queue.
These are single-application probe permissions, not multi-company authorization.

## Normal start / stop

```sh
python3 milestone0/scripts/native_setup.py
docker compose -f milestone0/compose.yaml up -d
docker compose -f milestone0/compose.yaml logs -f odoo
```

Stop the app before stopping PostgreSQL:

```sh
docker compose -f milestone0/compose.yaml stop
/opt/homebrew/opt/postgresql@16/bin/pg_ctl -D "$PWD/.local/milestone0/pgdata" -m fast stop
```

The database is retained under ignored `.local/milestone0/pgdata`. Docker retains
the separate `chainsql-m0_odoo-data` filestore volume. No boot-time system service
was added; run the start commands after a machine restart.

## Verify SQL installation and recovery

```sh
python3 milestone0/scripts/verify_native.py
npm --prefix milestone0/wallet test
npm --prefix milestone0/wallet run probe
```

The SQL test creates fresh `chainsql_verify_<suffix>` and
`chainsql_restore_<suffix>` databases and retains them for inspection. It exercises
real TCP credentials, rollback, simultaneous enqueue/claim, invalid claim tokens,
role denial, and an actual custom-format `pg_dump`/`pg_restore` round trip.
It also checks the accounting-only Odoo database's module states and denies the
worker access to `account_move`. These tests do not run live payments.

### Restore procedure established by the test

1. Install the same extension control/SQL files in the destination PostgreSQL.
2. Provision the three roles separately; do not embed passwords in the dump.
3. Create an empty destination database and run `install_extension.sql` there,
   so `chainsql_owner` owns the extension before restore.
4. Produce a restore TOC with `pg_restore --list backup.dump`. Comment out only
   the `SCHEMA - chainsql` creation entry, since step 3 created that schema.
5. Restore using `pg_restore --exit-on-error -L restore-list -d destination backup.dump`.
6. Compare runtime rows, ownership, permissions, and ability to claim pending work.

The exact implementation is in `verify_native.py`. PostgreSQL normally excludes
extension-owned table rows from dumps; `pg_extension_config_dump` registers the
operations table so pending requests and results are preserved. Precreating the
extension under the right role avoids restoring it under the administrator.

This proves **extension runtime data recovery**, not whole-Odoo disaster recovery.
Back up the Odoo filestore and wallet execution journal separately before future
use. After any real payment restoration, keep workers paused and reconcile with
Circle/on-chain outcomes before execution; a restored pending job is not permission
to send another payment. Probe claims intentionally have no production lease or
retry/reconciliation mechanism.

## Complete the Circle evidence

1. In [Circle Console](https://console.circle.com/), create a **test server API key**
   beginning `TEST_API_KEY:`. A `TEST_CLIENT_KEY:` is for frontend SDKs and will not
   authenticate this worker. [Circle key types](https://developers.circle.com/api-reference/keys).
2. Copy `milestone0/wallet/circle.env.example` to `.local/milestone0/circle.env`
   and fill in only the test API key in an editor. Set file permissions to `600`.
   Run `npm --prefix milestone0/wallet run setup`: it generates a 32-byte entity
   secret locally, registers its encrypted form, saves a private recovery file,
   creates two Arc-testnet EOAs, and fills the remaining configuration fields.
   It does not rotate an existing secret and stops on uncertain registration.
   The entity secret is generated by the developer, not issued with the API key.
   [Circle registration instructions](https://developers.circle.com/wallets/dev-controlled/register-entity-secret).
3. Fund only the printed sender address with test USDC from the [Circle Faucet](https://faucet.circle.com/).
4. Run the plan, then the single test transfer:

```sh
npm --prefix milestone0/wallet run transfer -- --plan
npm --prefix milestone0/wallet run transfer -- --submit
# If the existing transaction is still pending, observe it; do not create a new one:
npm --prefix milestone0/wallet run transfer -- --observe
```

The harness transfers exactly **0.01 test USDC**, with a maximum native gas budget
of **0.05 test USDC**, using Circle contract execution and `transfer(address,uint256)`.
It confirms the wallet is an Arc testnet EOA and writes its exact request and
idempotency key before submission. A submission with an unknown outcome stops for
reconciliation. A completed journal prevents another transfer on rerun.
Do not delete the journal to retry. An interrupted process may leave a lock;
check that no process remains and reconcile the journal before removing that lock.

Only an independently verified successful RPC receipt writes
`evidence/arc-transfer.json`: expected chain, sender, recipient, contract, calldata,
amount, zero native value, block hash, finalized height, token-emitter Transfer log,
and actual gas fee. The journal stays in ignored local storage. The user has a
Circle account; automated entity-secret registration, wallet creation, funding,
and Circle submission have **not** been performed in this baseline.

No x402 signing or settlement is enabled. The selected test facilitator currently
does not advertise Arc; see the separate capability matrix before selecting a
merchant or authorizing resource purchases.
