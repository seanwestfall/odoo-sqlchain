# ChainSQL

PostgreSQL command boundary, Odoo addons, restricted payment workers, and testnet integration evidence. Milestones 0–4 are included. Odoo is an upstream Git submodule, pinned to the revision used by the development pilot.

## Clone

```sh
git clone --recurse-submodules https://github.com/seanwestfall/odoo-sqlchain.git
cd odoo-sqlchain
```

If you already cloned without submodules:

```sh
git submodule update --init --depth 1 vendor/odoo
```

Odoo's upstream URL is `https://github.com/odoo/odoo.git`; the pinned commit is `7bbce824a1897a912441a7f0511ffec505cbe1d5`. The parent repository stores a gitlink, not Odoo's source history. Keep custom modules in `chainsql/odoo_addons`; changes inside the submodule belong to a separate Git repository.

## Layout

- `vendor/odoo/`: upstream Odoo source and standard addons (submodule).
- `chainsql/extension/`: native PostgreSQL extension and versioned migrations.
- `chainsql/odoo_addons/`: integration addons owned by this project.
- `chainsql/boundary/`, `chainsql/arc/`, `chainsql/x402/`: execution boundary and network adapters.
- `milestone0/` through `milestone4/`: setup instructions, scripts, tests, and historical evidence.
- `compose.local.yaml`, `LOCAL_BOM.md`: optional basic local Odoo demonstration.

## Setup

Start with [milestone 0](milestone0/README.md), then follow the milestone instructions in order. [Milestone 4](milestone4/README.md) documents the x402 resource purchase. Docker Compose now mounts upstream source from `vendor/odoo/odoo` and `vendor/odoo/addons`; custom addon paths are unchanged.

No credentials, wallets, databases, `.local` runtime state, virtual environments, installed Node packages, or Docker volumes are included. Provision a fresh disposable environment using the setup instructions. Existing evidence files document the original development instance; they are not proof that a fresh checkout has run those transactions.

The original development instance remains in `/Users/sean/Projects/odoo`. Do not start this checkout alongside it using the same ports and Compose project names: the defaults intentionally match the existing setup. Stop the old instance or adjust service names and ports before starting a new one. Existing payment journals and encryption keys must be migrated deliberately before recovering old payments; do not reconstruct them by issuing new approvals.

## Repository migration

This repository has fresh ChainSQL history and includes the milestone 4 work that was uncommitted in the original Odoo checkout. Original project commit: `0eb3d31d9420`. The original checkout and Git history are retained unchanged.

The migration is staged. Commit with your configured signing key, then publish the parent repository:

```sh
git commit -m "Initialize ChainSQL with pinned Odoo submodule"
git push -u origin main
```

The parent push does not upload Odoo's objects. If the destination already has an unrelated `main` branch, inspect it first or push a new branch; do not force-push over existing work. This migration does not publish anything automatically.

Upstream Odoo retains its own license in `vendor/odoo`. This migration does not change licensing or assign a new license to ChainSQL.
