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

## License

Internal use only.
