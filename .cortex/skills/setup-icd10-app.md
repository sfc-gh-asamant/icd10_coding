# ICD-10 Coding App — Setup & Customization Skill

This skill walks you through deploying and customizing the ICD-10 Retrieval-Grounded Coding Pipeline app on any Snowflake account.

## Overview

This package contains a Streamlit app + Snowflake backend that:
1. Ingests clinical encounter JSONL files
2. Extracts diagnoses from narratives using Cortex AI (claude-sonnet-4-6)
3. Retrieves candidate ICD-10 codes via Cortex Search (semantic similarity)
4. Assigns the best-fit code (grounded — no hallucinated codes)
5. Flags missed revenue where RA codes were found in notes but not billed

## Prerequisites

Before starting, confirm:
- [ ] You have a Snowflake account with **Cortex AI** enabled
- [ ] You have a role with `CREATE DATABASE` privileges (ACCOUNTADMIN or similar)
- [ ] You have a warehouse (any size — XS works for small datasets)
- [ ] Python 3.9+ and `pip` available locally
- [ ] Snowflake CLI (`snow`) configured with a default connection, OR a `~/.snowflake/connections.toml` with a `[default]` entry

## Step-by-Step Setup

### Step 1: Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 2: Configure your database and warehouse

Open `setup.sql` and find-and-replace these two placeholders:

| Placeholder | Replace with | Example |
|---|---|---|
| `{{DATABASE}}` | Your database name | `ICD10_CODING_DB` |
| `{{WAREHOUSE}}` | Your warehouse name | `COMPUTE_WH` |

Then run the script in Snowflake:

```bash
snow sql -f setup.sql
```

Or paste into a Snowflake worksheet and execute all.

### Step 3: Load ICD-10 reference data

The pipeline requires the **CMS FY2026 ICD-10-CM to HCC mappings** in the `ICD10_HCC_MAPPINGS` table. You have two options:

**Option A — From the CMS Excel file:**
1. Download "2026 Final ICD-10-CM Mappings" from [CMS.gov](https://www.cms.gov/medicare/health-plans/medicareadvtgspecratestats/risk-adjustors/model-software/icd-10-mappings)
2. Save as CSV
3. Load:
```sql
PUT 'file:///path/to/mappings.csv' @YOUR_DB.RAW.ENCOUNTER_STAGE/ref/;
COPY INTO YOUR_DB.RAW.ICD10_HCC_MAPPINGS
FROM @YOUR_DB.RAW.ENCOUNTER_STAGE/ref/mappings.csv
FILE_FORMAT = (TYPE='CSV' SKIP_HEADER=1 FIELD_OPTIONALLY_ENCLOSED_BY='"');
```

**Option B — From a shared dataset:**
If someone has shared the reference data with you as a CSV, place it in the `sample_data/` folder and load similarly.

### Step 4: Update the app config

Open `app.py` and edit the CONFIG section at the top:

```python
DATABASE = "ICD10_CODING_DB"          # ← your database from Step 2
RAW_SCHEMA = "RAW"                     # ← leave as-is unless you changed it
HARMONIZED_SCHEMA = "HARMONIZED"       # ← leave as-is unless you changed it
APP_TITLE = "HEDIS Optimizer"          # ← customize
BRAND_NAME = "Your Org"               # ← sidebar header
BRAND_SUBTITLE = "ICD-10 Coding"      # ← sidebar subheader
BRAND_COLOR = "#29B5E8"               # ← primary accent color
BRAND_COLOR_DARK = "#1B2A4A"          # ← dark accent color
```

### Step 5: Run the app

```bash
streamlit run app.py
```

### Step 6: Upload encounter data

Use the **Upload** page in the app to upload JSONL encounter files. Each line should be a JSON object with at minimum:

```json
{
  "MemberID": "M001",
  "MemberFirst": "Jane",
  "MemberLast": "Doe",
  "MemberDOB": "1955-03-15",
  "MemberGender": "Female",
  "ServiceStartDate": "2024-06-15",
  "DiagnosisCodes": [{"Code": "E11.9", "Qualifier": "ICD10"}],
  "Narratives": [{"Type": "Progress Note", "Value": "<p>Patient presents with...</p>"}]
}
```

The pipeline runs automatically within ~1 minute of upload via Stream + Task DAG.

## Customization Guide

### Changing the LLM model
In `setup.sql`, the stored procedures use `claude-sonnet-4-6`. To change:
- Search for `claude-sonnet-4-6` in `setup.sql` and replace with your preferred model
- Available: `llama3.1-70b`, `mistral-large2`, `claude-sonnet-4-6`, etc.

### Changing the embedding model
The Cortex Search service uses `snowflake-arctic-embed-m-v1.5`. To change, recreate the search service in `setup.sql` with a different `EMBEDDING_MODEL`.

### Adding branding
Edit the `BRAND_*` variables in the CONFIG section of `app.py`. The sidebar logo and colors are fully customizable via those variables.

### Adjusting the candidate count
The pipeline retrieves 10 candidate codes per diagnosis. To change, edit `limit` in `SP_RETRIEVE_CANDIDATES` (setup.sql).

## Troubleshooting

| Issue | Fix |
|---|---|
| "Cortex Search service not found" | Ensure `ICD10_HCC_MAPPINGS` has data before creating the search service |
| "No encounters loaded" | Upload JSONL via the Upload page or PUT to the stage |
| Tasks not running | Check `SHOW TASKS IN SCHEMA YOUR_DB.RAW` — they may need `ALTER TASK ... RESUME` |
| Cost page empty | ACCOUNT_USAGE has ~2hr latency; wait and refresh |
| Connection error | Verify `snow connection test` works, or check `~/.snowflake/connections.toml` |
