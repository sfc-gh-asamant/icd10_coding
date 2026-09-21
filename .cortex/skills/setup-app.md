# ICD-10 Coding App — Setup & Customization Skill

This skill walks you through deploying the ICD-10 Retrieval-Grounded Coding Pipeline **Streamlit app** on any Snowflake account.

## Overview

The app in `app/` is a Streamlit dashboard with 7 pages:
- **Dashboard** — missed RA codes, HEDIS measure eligibility
- **Action Queue** — prioritized review items with accept/reject workflow
- **Encounter Review** — drill into individual encounters with evidence highlighting
- **ICD-10 Reference** — browse 11,866 indexed ICD-10-CM codes
- **Pipeline** — architecture diagram, status metrics, manual trigger
- **Costs** — actual run costs + cost calculator for projections
- **Upload** — ingest new JSONL encounter files

## Prerequisites

- Snowflake account with **Cortex AI** enabled (COMPLETE + Cortex Search)
- Role with `CREATE DATABASE` privileges
- A warehouse (any size)
- Python 3.9+ with `pip`
- Snowflake CLI (`snow`) configured with a default connection

## Setup Steps

### Step 1: Install Python dependencies

```bash
pip install -r app/requirements.txt
```

### Step 2: Configure the Snowflake backend

Open `app/setup.sql` and find-and-replace:

| Placeholder | Replace with | Example |
|---|---|---|
| `{{DATABASE}}` | Your database name | `ICD10_CODING_DB` |
| `{{WAREHOUSE}}` | Your warehouse name | `COMPUTE_WH` |

Run the setup:
```bash
snow sql -f app/setup.sql
```

This creates the database, tables, views, stored procedures, Cortex Search service, and task DAG.

### Step 3: Load ICD-10 reference data

The `ICD10_HCC_MAPPINGS` table must be populated before the Cortex Search service can index.

**Option A — Use the included data (if you ran the pipeline setup first):**
The pipeline's `data/` folder contains `icd10_hcc_mappings_*.parquet` which has the same 11,866 codes. If you already loaded data via the pipeline, this table is already populated.

**Option B — From CMS directly:**
Download "2026 Final ICD-10-CM Mappings" from CMS.gov, save as CSV, and COPY INTO.

### Step 4: Update the app config

Edit the CONFIG section at the top of `app/app.py`:

```python
DATABASE = "ICD10_CODING_DB"          # your database from Step 2
APP_TITLE = "HEDIS Optimizer"          # customize
BRAND_NAME = "Your Org"               # sidebar header
BRAND_COLOR = "#29B5E8"               # primary accent color
```

### Step 5: Run the app

```bash
streamlit run app/app.py
```

### Step 6: Upload encounter data

Use the **Upload** page to upload JSONL encounter files. The pipeline auto-triggers within ~1 minute.

Each JSONL line should have at minimum:
```json
{
  "MemberID": "M001",
  "MemberFirst": "Jane",
  "MemberLast": "Doe",
  "MemberDOB": "1955-03-15",
  "ServiceStartDate": "2024-06-15",
  "DiagnosisCodes": [{"Code": "E11.9", "Qualifier": "ICD10"}],
  "Narratives": [{"Type": "Progress Note", "Value": "<p>Patient presents with...</p>"}]
}
```

## Customization

- **LLM model:** Search for `claude-sonnet-4-6` in `app/setup.sql` and replace
- **Embedding model:** Edit the Cortex Search service in `app/setup.sql`
- **Candidate count:** Edit `limit` in `SP_RETRIEVE_CANDIDATES`
- **Branding:** Edit `BRAND_*` variables in `app/app.py`

## Troubleshooting

| Issue | Fix |
|---|---|
| "Cortex Search service not found" | Load `ICD10_HCC_MAPPINGS` before creating the search service |
| Tasks not running | `SHOW TASKS IN SCHEMA YOUR_DB.RAW` — may need `ALTER TASK ... RESUME` |
| Cost page empty | ACCOUNT_USAGE has ~2hr latency |
| Connection error | Verify `snow connection test` works |
