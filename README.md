# ICD-10 Retrieval-Grounded Coding Pipeline

An end-to-end ICD-10 medical coding system built on Snowflake Cortex AI. Extracts diagnoses from clinical encounter narratives, assigns real ICD-10-CM codes (grounded, never hallucinated), and evaluates accuracy against ground truth.

## Repository Structure

```
icd10_coding/
├── app/                          Streamlit dashboard for reviewing results
│   ├── app.py                      7-page app (Dashboard, Action Queue, Encounter Review, etc.)
│   ├── setup.sql                   Snowflake DDL for app backend (tables, views, procs, tasks)
│   └── requirements.txt            Python dependencies
│
├── pipeline/                     Data processing pipeline (notebooks)
│   ├── setup.sql                   Snowflake DDL for pipeline environment
│   ├── setup.py                    Automated setup script (Snowpark)
│   └── notebooks/
│       ├── 00_setup.ipynb            Parse encounters, build enriched ICD-10 corpus
│       ├── 01_extraction.ipynb       LLM extraction of clinical findings
│       ├── 02_search.ipynb           Multi-path ICD-10 candidate retrieval (Cortex Search)
│       ├── 03_matching.ipynb         LLM code assignment with confidence scoring
│       ├── 04_evaluation.ipynb       Evaluate pipeline against ground truth
│       └── 05_run_experiment.ipynb   Consolidated end-to-end runner
│
├── data/                         Input data (parquet files)
│   ├── encounters_*.parquet          1,340 clinical encounters with narratives
│   ├── ground_truth_*.parquet        2,275 validated ICD-10 assignments
│   ├── icd10_codes_*.parquet         74,260 ICD-10-CM codes (full reference)
│   ├── icd10_hcc_mappings_*.parquet  11,866 ICD-10 to HCC mappings (CMS FY2026)
│   └── hcc_mappings_*.parquet        20,500 HCC category/RAF coefficients
│
└── .cortex/skills/               CoCo skills for guided setup
    ├── setup-app.md                 Walks through app deployment
    └── setup-pipeline.md            Walks through pipeline setup
```

## What You Can Do

### Option 1: Run the Pipeline Only

Process clinical encounters through the AI coding pipeline and evaluate accuracy.

1. Set up the Snowflake environment using `pipeline/setup.sql`
2. Load the included parquet data from `data/`
3. Run the notebooks in order (00 through 04)

**CoCo shortcut:** Open this repo in Cortex Code and reference the `setup-pipeline` skill.

### Option 2: Run the App Only

Deploy the Streamlit dashboard to review AI-assigned codes, manage action queues, and track costs.

1. Set up the Snowflake backend using `app/setup.sql`
2. Load ICD-10 reference data (from `data/` or CMS.gov)
3. Run `streamlit run app/app.py`

**CoCo shortcut:** Open this repo in Cortex Code and reference the `setup-app` skill.

### Option 3: Run Both

Run the pipeline first to process the included 1,340 encounters, then spin up the app to review results interactively. The pipeline populates the same `CHART_REVIEW_DB` database that the app reads from.

1. Follow the pipeline setup (Option 1)
2. Then follow the app setup (Option 2) — the data is already loaded

## Architecture

```
Clinical encounter JSONL/parquet
    │
    ▼
Step 1: EXTRACT — Cortex AI (claude-sonnet) extracts diagnoses from narratives
    │
    ▼
Step 2: SEARCH — Cortex Search retrieves top-10 real ICD-10-CM candidate codes
    │
    ▼
Step 3: MATCH — Cortex AI picks the single best-fit code (MUST be from candidates)
    │
    ▼
Step 4: EVALUATE — Compare against ground truth with LLM judge
    │
    ▼
Streamlit App — Dashboard, Action Queue, Encounter Review, Cost Calculator
```

Every assigned code is a real CMS billable code — the retrieval-grounded approach ensures no hallucinated codes.

## Prerequisites

- Snowflake account with **Cortex AI** enabled
- `ACCOUNTADMIN` role (or equivalent)
- A warehouse (default: `COMPUTE_WH`)
- Python 3.9+ (for the Streamlit app)
- Snowflake CLI (`snow`) configured

## Getting Started

### Setting Up the Pipeline

The pipeline loads the included sample data (1,340 encounters + ground truth) into Snowflake, then runs a sequence of notebooks that extract diagnoses, retrieve candidate ICD-10 codes, assign best-fit codes, and evaluate accuracy.

**Using the CoCo skill (recommended):**

1. Clone this repo and open it in [Cortex Code](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code)
2. Reference the **`setup-pipeline`** skill — it will walk you through every step interactively, including configuring your warehouse/role, uploading data, loading tables, and running notebooks in order

**Manual setup:**

1. Edit `pipeline/setup.sql` — set your `WAREHOUSE_NAME` and `ROLE_NAME` at the top
2. Run the SQL to create databases, schemas, tables, and the data loading stage:
   ```bash
   snow sql -f pipeline/setup.sql
   ```
3. Upload the parquet files from `data/` to the stage:
   ```sql
   PUT file:///path/to/data/encounters_*.snappy.parquet
       @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/encounters/ AUTO_COMPRESS=FALSE;
   -- repeat for ground_truth, icd10_hcc_mappings, icd10_codes, hcc_mappings
   ```
   Or use the automated script in a Snowflake notebook:
   ```python
   from pipeline.setup import run_setup
   run_setup(session, data_dir="/path/to/data")
   ```
4. Run the COPY INTO statements (Section 4 of `pipeline/setup.sql`) and verify row counts
5. Upload notebooks from `pipeline/notebooks/` to a Snowflake workspace and run in order:
   - `00_setup.ipynb` (always first — creates derived tables)
   - `01_extraction.ipynb` through `04_evaluation.ipynb` in sequence
   - Or use `05_run_experiment.ipynb` to run steps 01–04 in one shot

### Setting Up the App

The Streamlit app provides a dashboard for reviewing AI-assigned codes, managing an action queue with accept/reject workflow, inspecting individual encounters with evidence highlighting, and projecting costs at scale.

**Using the CoCo skill (recommended):**

1. Clone this repo and open it in [Cortex Code](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code)
2. Reference the **`setup-app`** skill — it will guide you through configuring your database, loading reference data, customizing branding, and running the app

**Manual setup:**

1. Install Python dependencies:
   ```bash
   pip install -r app/requirements.txt
   ```
2. Edit `app/setup.sql` — find-and-replace `{{DATABASE}}` with your database name and `{{WAREHOUSE}}` with your warehouse name
3. Run the SQL to create the app backend (tables, views, stored procedures, Cortex Search service, task DAG):
   ```bash
   snow sql -f app/setup.sql
   ```
4. Load ICD-10 reference data into the `ICD10_HCC_MAPPINGS` table. If you already ran the pipeline setup, this table is already populated. Otherwise, load from the included `data/icd10_hcc_mappings_*.parquet` or download from CMS.gov.
5. Edit the CONFIG section at the top of `app/app.py` — set your `DATABASE` name and customize branding (`BRAND_NAME`, `BRAND_COLOR`, etc.)
6. Run the app:
   ```bash
   streamlit run app/app.py
   ```
7. Upload encounter data via the **Upload** page, or use the data already loaded by the pipeline

### Setting Up Both (Pipeline + App)

To get the full experience — process encounters through the pipeline, then review results in the app:

1. **Run the pipeline setup first** (see above) — this loads all data and processes encounters through the AI coding pipeline
2. **Then run the app setup** — since the pipeline already created `CHART_REVIEW_DB` and loaded data, the app setup only needs to add its views, stored procedures, and task DAG on top
3. Edit `app/setup.sql` to use `CHART_REVIEW_DB` as the `{{DATABASE}}` value, then run it
4. Start the app with `streamlit run app/app.py`

The pipeline and app share the same `CHART_REVIEW_DB` database, so pipeline results are immediately visible in the app.

## CoCo Skills Reference

This repo includes two [Cortex Code](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code) skills in `.cortex/skills/` that provide step-by-step guided setup:

| Skill | File | What It Does |
|-------|------|-------------|
| **setup-pipeline** | `.cortex/skills/setup-pipeline.md` | Walks through pipeline environment setup, data loading, and notebook execution |
| **setup-app** | `.cortex/skills/setup-app.md` | Walks through app backend setup, branding customization, and deployment |

To use a skill: clone the repo, open it in Cortex Code, and reference the skill name in conversation. The agent will guide you through each step interactively.

## License

Internal use only.
