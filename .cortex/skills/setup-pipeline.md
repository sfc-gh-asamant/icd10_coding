# ICD-10 Coding Pipeline — Setup & Run Skill

This skill walks you through setting up and running the ICD-10 clinical coding **pipeline** — the data processing backend that extracts diagnoses from clinical notes, retrieves candidate ICD-10 codes, assigns best-fit codes, and evaluates accuracy against ground truth.

## Overview

The pipeline in `pipeline/` consists of 6 Snowflake notebooks that run in sequence:

| Order | Notebook | What It Does |
|-------|----------|-------------|
| 1 | `00_setup.ipynb` | Parses encounters into sections, builds enriched ICD-10 corpus, seeds dual-code pairs |
| 2 | `01_extraction.ipynb` | LLM extracts clinical findings from encounter notes |
| 3 | `02_search.ipynb` | Retrieves ICD-10 candidates via Cortex Search + similarity + HCC expansion |
| 4 | `03_matching.ipynb` | LLM assigns best ICD-10 code per finding |
| 5 | `04_evaluation.ipynb` | Evaluates against ground truth, logs metrics |
| 6 | `05_run_experiment.ipynb` | (Optional) Runs steps 01–04 in one notebook |

The `data/` folder contains all input data as parquet files:
- **1,340 clinical encounters** with narratives and diagnosis codes
- **2,275 ground truth** validated ICD-10 assignments
- **74,260 ICD-10-CM codes** (full reference set)
- **11,866 ICD-10 to HCC mappings** (CMS FY2026)
- **20,500 HCC category/RAF coefficients**

## Prerequisites

- Snowflake account with **Cortex AI** enabled (COMPLETE + Cortex Search)
- Access to `claude-4-sonnet` model (or edit the model name in notebooks)
- `ACCOUNTADMIN` role (or equivalent)
- A warehouse (default: `COMPUTE_WH`)

## Setup Steps

### Step 1: Configure warehouse and role

Open `pipeline/setup.sql` and edit the top section if your environment differs:

```sql
SET WAREHOUSE_NAME = 'COMPUTE_WH';   -- change if needed
SET ROLE_NAME      = 'ACCOUNTADMIN';  -- change if needed
```

### Step 2: Create databases, schemas, and tables

Run Sections 0–2 of `pipeline/setup.sql`:

```bash
snow sql -f pipeline/setup.sql
```

Or paste into a Snowflake worksheet and run section by section.

### Step 3: Upload data to stage

Upload the parquet files from `data/` to the Snowflake stage:

```sql
PUT file:///path/to/data/encounters_*.snappy.parquet
    @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/encounters/ AUTO_COMPRESS=FALSE;

PUT file:///path/to/data/ground_truth_*.snappy.parquet
    @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/ground_truth/ AUTO_COMPRESS=FALSE;

PUT file:///path/to/data/icd10_hcc_mappings_*.snappy.parquet
    @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/icd10_hcc_mappings/ AUTO_COMPRESS=FALSE;

PUT file:///path/to/data/icd10_codes_*.snappy.parquet
    @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/icd10_codes/ AUTO_COMPRESS=FALSE;

PUT file:///path/to/data/hcc_mappings_*.snappy.parquet
    @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/hcc_mappings/ AUTO_COMPRESS=FALSE;
```

Replace `/path/to/data/` with the actual path to the `data/` folder.

**Automated alternative:** Use `pipeline/setup.py` in a Snowflake notebook Python cell:

```python
from setup import run_setup
run_setup(session, data_dir="/path/to/data")
```

### Step 4: Load data into tables

Run Sections 4–6 of `pipeline/setup.sql` (COPY INTO statements + verification).

Expected row counts:
| Table | Rows |
|---|---|
| ENCOUNTERS | 1,340 |
| AETNA_GROUND_TRUTH | 2,275 |
| ICD10_HCC_MAPPINGS | 11,866 |
| ICD10_CODES | 74,260 |
| HCC_MAPPINGS | 20,500 |

### Step 5: Run the notebooks

Upload the notebooks from `pipeline/notebooks/` to a Snowflake workspace, then run in order:

1. **`00_setup.ipynb`** — creates derived tables (DOCUMENT_SECTIONS, enriched corpus, dual-code pairs)
2. **`01_extraction.ipynb`** — LLM extracts clinical findings (moderate time, LLM calls)
3. **`02_search.ipynb`** — retrieves ICD-10 candidates via Cortex Search
4. **`03_matching.ipynb`** — LLM assigns best-fit codes (moderate time, LLM calls)
5. **`04_evaluation.ipynb`** — evaluates against ground truth using LLM judge

Or use **`05_run_experiment.ipynb`** to run steps 01–04 in one go (still needs 00_setup first).

## Snowflake Objects Created

| Database | Schema | Purpose |
|----------|--------|---------|
| `CHART_REVIEW_DB` | `RAW` | Source encounters, ground truth, ICD-10/HCC mappings |
| `ICD10_CODING_APP` | `PROCESSING` | Parsed sections, extracted findings |
| `ICD10_CODING_APP` | `MATCHING` | Search candidates, final ICD-10 assignments |
| `ICD10_CODING_APP` | `EXPERIMENTS` | Evaluation results, run tracking |
| `ICD10_CODING_APP` | `ICD10_REF` | Reference data (ICD-10 codes, HCC mappings) |

## Customization

- **Model:** All notebooks use `claude-4-sonnet`. Change `EXTRACTION_MODEL`, `MATCHING_MODEL`, and `EVAL_MODEL` at the top of each notebook.
- **Warehouse:** Edit `$WAREHOUSE_NAME` in `pipeline/setup.sql`.
- **Role:** Edit `$ROLE_NAME` in `pipeline/setup.sql`.

## Troubleshooting

| Issue | Fix |
|---|---|
| "Model not available" | Ensure Cortex AI is enabled and the model is available in your region |
| COPY INTO shows 0 rows | Verify parquet files are at correct stage paths |
| Cortex Search fails | Ensure warehouse is running and you have CREATE CORTEX SEARCH SERVICE privilege |
