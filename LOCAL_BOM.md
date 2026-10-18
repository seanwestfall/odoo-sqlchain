# Local Odoo: Vendor Bills and Bills of Materials

This setup runs the pinned Odoo submodule's server and addons using the Odoo 19
Docker runtime and a separate PostgreSQL 16 database. Manufacturing (`mrp`)
provides Bills of Materials. Invoicing (`account`) provides Vendor Bills.
Demo data includes example products, BOMs, and accounting records.

## Open the app

- Vendor Bills: http://localhost:8069/odoo/vendor-bills
- Bills of Materials: http://localhost:8069/odoo/boms
- Database: `odoo_bom`
- Login: `admin`
- Password: `admin`
- Vendor Bills menu: Invoicing → Vendors → Bills
- BOM menu: Manufacturing → Products → Bills of Materials

These are local demo credentials. The web port binds to `127.0.0.1` only;
PostgreSQL is not exposed to the host.

## Start or stop

Initialize `vendor/odoo` with `git submodule update --init --depth 1` first.
Run from this repository with Docker Desktop running:

```sh
docker compose -f compose.local.yaml up -d
docker compose -f compose.local.yaml logs -f odoo
docker compose -f compose.local.yaml stop
```

Docker volumes preserve the database and uploaded files across restarts.
Source files are mounted read-only into the container. After editing Python,
restart the server with `docker compose -f compose.local.yaml restart odoo`.

## First-time setup on a fresh machine

Create the ignored local configuration with a random database-manager password:

```sh
mkdir -p .local
python3 - <<'PY'
from pathlib import Path
import secrets
p = Path('.local/odoo.conf')
if not p.exists():
    p.write_text(
        '[options]\n'
        'addons_path = /mnt/extra-addons\n'
        'data_dir = /var/lib/odoo\n'
        'admin_passwd = ' + secrets.token_urlsafe(32) + '\n'
    )
PY
docker compose -f compose.local.yaml up -d db
docker compose -f compose.local.yaml run --rm odoo odoo -d odoo_bom -i mrp,account --with-demo --stop-after-init --no-http
docker compose -f compose.local.yaml up -d
```

Only run the initialization command for a new database. Normal starts use the
commands above and retain your changes. The generated database-manager password
is separate from the web login; database listing/management is disabled in the
running app.
