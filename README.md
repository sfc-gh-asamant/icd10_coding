# ICD-10 Retrieval-Grounded Coding Pipeline

A Streamlit app + Snowflake backend that uses Cortex AI to extract ICD-10 codes from clinical narratives, grounded in real CMS reference codes (no hallucinated codes).

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure `setup.sql`** — replace `{{DATABASE}}` and `{{WAREHOUSE}}` with your values

3. **Run the SQL setup:**
   ```bash
   snow sql -f setup.sql
   ```

4. **Load ICD-10 reference data** into `ICD10_HCC_MAPPINGS` (see skill docs for details)

5. **Edit `app.py`** — update the CONFIG section at the top with your database name and branding

6. **Run the app:**
   ```bash
   streamlit run app.py
   ```

For detailed instructions, use the CoCo skill: open this project in Cortex Code and type `/setup-icd10-app`.

## What's Included

| File | Purpose |
|---|---|
| `app.py` | Streamlit app (7 pages: Dashboard, Action Queue, Encounter Review, ICD-10 Reference, Pipeline, Costs, Upload) |
| `setup.sql` | All Snowflake DDL: database, tables, views, stored procedures, Cortex Search service, task DAG |
| `requirements.txt` | Python dependencies |
| `.cortex/skills/setup-icd10-app.md` | CoCo skill with full setup + customization guide |
| `sample_data/` | Place your JSONL encounter files and ICD-10 reference CSV here |

## Architecture

```
JSONL files → Upload page → @ENCOUNTER_STAGE → Stream detects INSERT
    ↓
Step 1: AI_COMPLETE (claude-sonnet) extracts diagnoses from narratives
    ↓
Step 2: Cortex Search retrieves top-10 real ICD-10 candidate codes
    ↓
Step 3: AI_COMPLETE picks single best-fit code (MUST be from candidate list)
    ↓
Serving view: flags MISSED_REVENUE where RA codes found in notes but not billed
```

## Requirements

- Snowflake account with Cortex AI enabled
- Python 3.9+
- Snowflake CLI (`snow`) or `connections.toml` configured
