# SupplyChain360

A runnable, local manufacturing and supply chain automation project, built as six learning stages. Uses synthetic data; no external messages are sent.

## Start here

Requires Python 3.12. Clone the repository, then open PowerShell in the project folder and run:

```powershell
.\start.ps1
```

Open **http://127.0.0.1:8000** for the dashboard and **http://127.0.0.1:8000/docs** for the interactive API. Leave the terminal running. Press Ctrl+C to stop.

If another server is already using port 8000, stop it before starting this application.

If your PowerShell policy blocks scripts, use these commands directly (no policy changes required):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m app.cli demo
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`requirements.lock.txt` records the tested versions; `requirements.txt` states allowed dependency ranges.

## Stage 1 — Model the business in SQL

**What happened:** `app/db.py` creates seven tables. Suppliers provide products; products are identified by SKU; purchase orders reference those products. Alerts, notifications, runs and audit records preserve operational history.

**Why it matters:** SQLite stores data between restarts. Primary keys prevent duplicate identities. Foreign keys prevent references to missing products or suppliers. Each operational import is a complete snapshot, not a stock increment.

**Read:** `app/db.py`, then `app/demo.py`.

**Try:** Open `runtime/source/inventory.csv`. RM-001 has 18 units and a reorder point of 30. RM-002 has no available stock. These are deliberately created problems.

The demo command generates CSV, an upstream SQLite database and a JSON bundle using relative dates. Running `demo` again overwrites the demo source files and reloads them; use `run` to process your edits without resetting them.

## Stage 2 — Extract, transform, load

**What happened:** `app/etl.py` reads a source into Pandas DataFrames, trims text, normalizes order statuses, converts numeric columns and validates business rules. Only validated data reaches SQLite. Delete and insert operations share one transaction, so an insert failure rolls back the replacement.

**Why it matters:** A CSV may say `shipped`, ` SHIPPED ` or contain an invalid quantity. Transformation standardizes the first two; validation rejects the bad quantity rather than silently corrupting stock.

**Try:** Change RM-001's quantity and counted quantity to 50. Save the CSV and click **Run workflow**. Its low-stock alert resolves. Other alerts remain.

Then enter `-1` as a quantity. Run again. The workflow fails, the prior valid snapshot remains, and a failure appears in the outbox. Restore the value before continuing.

### Three supported sources

```powershell
# CSV folder: suppliers.csv, inventory.csv, purchase_orders.csv
.\.venv\Scripts\python.exe -m app.cli run

# Read a relational source (SQLite adapter)
.\.venv\Scripts\python.exe -m app.cli run --source sqlite --location runtime/source/upstream.db

# REST source: JSON object with suppliers, inventory, purchase_orders arrays
.\.venv\Scripts\python.exe -m app.cli run --source api --location http://127.0.0.1:9001/bundle.json
```

To try the last command with a real local HTTP endpoint, first run this in a separate terminal:

```powershell
.\.venv\Scripts\python.exe -m http.server 9001 --bind 127.0.0.1 --directory runtime/source
```

The source schemas match the generated CSV headers. Supply all three datasets on each import. Empty datasets must still supply the required columns; the JSON adapter expects nonempty arrays. This is a snapshot contract, not a general connector for arbitrary ERP schemas. Real supplier APIs need an adapter for their payload and authentication.

## Stage 3 — Turn business conditions into rules

**What happened:** `app/rules.py` detects:

| Rule | Trigger |
|---|---|
| Low stock | Available quantity is at or below reorder point; zero is critical |
| Inventory discrepancy | System quantity differs from physical count |
| Delayed shipment | Undelivered order's expected date is before today |
| Pending order | Order remains pending three or more days after ordering |

Each alert has a stable key such as `low_stock:RM-001`. Repeated runs update the same alert. A new occurrence creates a notification; resolution creates a resolution notice; recurrence creates a new notice. An alert continuously active for 24 hours gets one escalation on the next workflow run.

**Try:** Run the unchanged demo twice. You should still have five active exceptions and five initial notifications, rather than ten duplicate notifications.

**Important business distinction:** Counting and available stock are independent observations. This project flags discrepancies; it does not automatically change quantities or place orders.

## Stage 4 — Expose data and calculate KPIs

**What happened:** `app/main.py` serves FastAPI endpoints. `app/analytics.py` calculates KPIs in SQL. `static/index.html` fetches the endpoints and displays the results.

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Server health |
| `GET /api/kpis` | KPI results and supplier performance |
| `GET /api/data/inventory` | Current inventory |
| `GET /api/data/purchase_orders` | Current orders |
| `GET /api/data/alerts` | Active and resolved alert records |
| `GET /api/data/runs` | Workflow execution history |
| `GET /api/data/notifications` | Local notification outbox |
| `GET /api/data/audit` | Audit events |
| `POST /api/workflows/run` | Run configured local CSV import; JSON content type required |
| `GET /api/reports/latest` | Download latest successful JSON report |

### Understand the numbers

| KPI | Definition | Fresh demo |
|---|---|---|
| Stock availability | SKUs with quantity > 0 / total SKUs | 75% |
| On-time delivery | Delivered orders received by expected date / delivered orders | 50% |
| Active exceptions | Active rule/entity pairs | 5 |
| Exception rate | Distinct affected inventory and order entities / all inventory and order entities | 62.5% |
| Inventory turnover | Consumed quantity × unit cost / average opening and closing inventory value | Calculated from source |
| Workflow completion | Successful runs / completed runs | 100% before any failures |
| SLA adherence | Successful runs with ETL and rule processing ≤30 seconds / completed runs | Measured |
| Processing time | Average recorded execution duration | Measured, not a promised speedup |

Undefined ratios show a dash. Turnover uses opening stock and consumption supplied for the same reporting period across all SKUs. It is a period consumption-cost ratio, not an annualized accounting claim. Currency is unspecified and must be consistent. Late open orders are reflected in exceptions; the supplier delivery percentage uses completed orders only. No measured before/after efficiency improvement is claimed.

## Stage 5 — Reliability and scheduling

**What happened:** `app/workflow.py` coordinates extraction, validation, loading, rules, run recording and reports. Transient network errors, HTTP 429/5xx and database locks get up to three attempts with exponential backoff. Data errors and other HTTP client errors fail immediately.

`runtime/execution.log` stores execution logs. SQLite stores audit events and failure notifications. `runtime/reports/run-N.json` stores successful reports. In-process and database locks prevent overlapping workflow execution against the same runtime directory, including a scheduler and API running together.

Start a scheduler in another terminal:

```powershell
.\.venv\Scripts\python.exe -m app.cli schedule --interval 300
```

It runs immediately, then waits five minutes after each finished attempt. It continues after failures. The terminal must remain open; Ctrl+C stops it. No Windows scheduled task or cloud automation is installed. The app defaults to the Asia/Kolkata business timezone; override `SC360_TIMEZONE` if necessary. `SC360_DATA_DIR` selects another runtime directory.

**Limits to understand:** Data loading is atomic, but the entire multi-stage workflow is not one transaction. If reporting fails after loading, the loaded snapshot remains and the run is marked failed. A process forcibly terminated mid-run may leave a `running` history record; locks release when the process exits. This teaching scheduler has no crash recovery or exactly-once delivery guarantee. Notifications are durable local outbox entries, not email, Slack or SMS delivery.

## Stage 6 — Verify behavior

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use isolated temporary databases. They cover expected KPIs, duplicate suppression, invalid imports preserving old data, transaction rollback, escalation, resolution, reopening, source adapters, retry behavior, API responses and downloads.

The API source unit test mocks the supplier response; a local HTTP smoke test also checks a real JSON endpoint. This does not verify any real supplier integration.

## Where to go after understanding this version

This is a functional local MVP. Before using it as a shared production service, add authentication and roles, replace demo source contracts with actual ERP/supplier mappings, configure an authorized notification delivery provider, and add migrations, backups and a managed scheduler. It currently binds only to localhost and has no user accounts.

Official references used: [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/), [FastAPI lifespan testing](https://fastapi.tiangolo.com/advanced/testing-events/), [Pandas CSV input](https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html), [Pandas numeric conversion](https://pandas.pydata.org/docs/reference/api/pandas.to_numeric.html).

## Git Bash setup

```bash
git clone https://github.com/shivgithub1234/SupplyChain360.git
cd SupplyChain360
py -3.12 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
./.venv/Scripts/python.exe -m app.cli demo
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal, run tests with `./.venv/Scripts/python.exe -m pytest -q`.
