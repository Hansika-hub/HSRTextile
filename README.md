# HSR Textiles ERP

An Odoo 19 Community module (`textile_inventory`) for a textile weaving and job-work unit. It covers the full flow from the vendor's order to the worker's pay:

**Vendor order → Material receipt → Godown stock → Loom allocation → Weaving production → Finished fabric rolls → Dispatch → Mill reconciliation → Worker pay → Dashboard**

Current version: `19.0.1.7.0`

## Features

| Area | What it does |
|---|---|
| Vendor orders | Order reference per vendor, required fabric, expected yarn and Pavu, live progress (received, woven, rolled, dispatched, accepted by the mill) |
| Yarn receipts | Bag size × number of bags = kg, posted to godown stock |
| Pavu receipts | Several roll lengths on one receipt, totals in metres, empty-roll log |
| Looms | Loom master, status, breakdown history, yarn allocation (blocked for a loom in breakdown or above available stock) |
| Production | Day (7 AM–7 PM) and night (7 PM–7 AM) shift entries, one or more workers, damaged / waste / rejected metres inside metres produced |
| Finished fabric | Uniquely numbered rolls (default 130–140 m, configurable per order) linked to the shifts they were woven in |
| Dispatch | One load per vendor (several of that vendor's orders allowed), vehicle and driver, printable dispatch note |
| Mill reconciliation | Accepted, rejected and missing metres per load, with correction history |
| Worker pay | Configurable per-metre rates, pay sheets (calculate, approve, paid), summaries by worker, shift and month |
| Dashboard | Stock, loom use, production, pending orders, dispatch and mill differences, pay due |
| Security | Five roles (owner, administrator, inventory manager, production supervisor, accountant), audit history on key fields |

Stock is never edited directly. Every movement is a standard Odoo stock transfer (`stock.picking`), in kilograms for yarn and metres for Pavu and fabric. Confirmed documents are locked; corrections are reversals or new entries.

## Repository layout

```
textile_inventory/   The Odoo module (models, views, security, reports, migrations, tests)
deploy/              Docker deployment (Odoo, PostgreSQL, Caddy HTTPS, nightly backup, scripts)
```

## Requirements

- Odoo 19 Community (source install) and Python 3.12 or newer
- PostgreSQL 16

## Quick start (development)

Place this repository inside your Odoo `custom-addons` folder and make sure `addons_path` in `odoo.conf` includes it. Then:

```bash
# new database with the module installed
createdb HSRTextile_new
python odoo-bin -c odoo.conf -d HSRTextile_new -i textile_inventory --stop-after-init

# run the server
python odoo-bin -c odoo.conf -d HSRTextile_new

# upgrade after changing the code
python odoo-bin -c odoo.conf -d HSRTextile_new -u textile_inventory --stop-after-init
```

Open `http://localhost:8069`.

## Deployment with Docker

The `deploy/` folder holds a stack with PostgreSQL 16, Odoo 19, a Caddy HTTPS proxy and a nightly backup service. Only ports 80 and 443 are exposed; the database and Odoo are not published.

```bash
cd deploy
cp .env.example .env        # then fill in DOMAIN, DB_NAME and two strong secrets
./scripts/init-db.sh        # first time, empty database
docker compose up -d
./scripts/healthcheck.sh    # every line should say OK
```

## License

MIT — see [LICENSE](https://www.apache.org/licenses/LICENSE-2.0.txt)
