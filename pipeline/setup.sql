-- ICD-10 Coding Pipeline: Full Environment Setup
-- Co-authored with CoCo
--
-- This script sets up the complete Snowflake environment for the ICD-10
-- clinical coding experiments pipeline. Run this BEFORE the notebooks.
--
-- PREREQUISITES:
--   1. ACCOUNTADMIN role (or equivalent with CREATE DATABASE, CREATE WAREHOUSE)
--   2. A warehouse (default: COMPUTE_WH) — change below if needed
--   3. The data/ parquet files uploaded to a stage (see INSTRUCTIONS below)
--
-- INSTRUCTIONS:
--   1. Create a workspace and upload this entire package (or clone from git)
--   2. Run this SQL script section-by-section in a Snowsight worksheet
--   3. Then run the notebooks in order: 00_setup → 01 → 02 → 03 → 04 → 05
--
-- =============================================================================
-- SECTION 0: Configuration — edit these if your environment differs
-- =============================================================================

SET WAREHOUSE_NAME = 'COMPUTE_WH';
SET ROLE_NAME      = 'ACCOUNTADMIN';

USE ROLE IDENTIFIER($ROLE_NAME);
USE WAREHOUSE IDENTIFIER($WAREHOUSE_NAME);

-- =============================================================================
-- SECTION 1: Create databases and schemas
-- =============================================================================

-- Source data database
CREATE DATABASE IF NOT EXISTS CHART_REVIEW_DB;
CREATE SCHEMA IF NOT EXISTS CHART_REVIEW_DB.RAW;

-- Application database
CREATE DATABASE IF NOT EXISTS ICD10_CODING_APP;
CREATE SCHEMA IF NOT EXISTS ICD10_CODING_APP.PROCESSING;
CREATE SCHEMA IF NOT EXISTS ICD10_CODING_APP.MATCHING;
CREATE SCHEMA IF NOT EXISTS ICD10_CODING_APP.EXPERIMENTS;
CREATE SCHEMA IF NOT EXISTS ICD10_CODING_APP.ICD10_REF;

-- =============================================================================
-- SECTION 2: Create source tables
-- =============================================================================

CREATE TABLE IF NOT EXISTS CHART_REVIEW_DB.RAW.ENCOUNTERS (
    ENCOUNTER_ID       VARCHAR(50)   DEFAULT UUID_STRING(),
    SOURCE_FILE        VARCHAR(200),
    ENCOUNTER_SEQ      VARCHAR(50),
    SERVICE_START_DATE TIMESTAMP_NTZ,
    SERVICE_END_DATE   TIMESTAMP_NTZ,
    CCD_STATUS         VARCHAR(20),
    MEMBER_ID          VARCHAR(50),
    MEMBER_FIRST       VARCHAR(100),
    MEMBER_LAST        VARCHAR(100),
    MEMBER_DOB         DATE,
    MEMBER_GENDER      VARCHAR(20),
    MEMBER_ADDRESS     VARCHAR(200),
    MEMBER_CITY        VARCHAR(100),
    MEMBER_STATE       VARCHAR(5),
    MEMBER_ZIP         VARCHAR(10),
    OID                VARCHAR(200),
    PROVIDER_TIN       VARCHAR(50),
    SOURCE_SYSTEM      VARCHAR(50),
    CDR_LOAD_DATE      TIMESTAMP_NTZ,
    DIAGNOSIS_CODES    VARIANT,
    NARRATIVES         VARIANT,
    PERFORMERS         VARIANT,
    RAW_RECORD         VARIANT,
    LOADED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    BATCH              VARCHAR
);

CREATE TABLE IF NOT EXISTS CHART_REVIEW_DB.RAW.AETNA_GROUND_TRUTH (
    CHASE_ID              VARCHAR,
    DIAGNOSIS_CODE        VARCHAR,
    ICD_CODE_DISPOSITION  VARCHAR,
    DISPOSITION_REASON    VARCHAR,
    DOS_START_DATE        DATE,
    DOS_END_DATE          DATE,
    BATCH                 VARCHAR DEFAULT 'BATCH_01',
    LOADED_AT             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS CHART_REVIEW_DB.RAW.ICD10_HCC_MAPPINGS (
    ICD_CODE          VARCHAR(10),
    DESCRIPTION       VARCHAR(500),
    HCC_ESRD_V21      VARCHAR(10),
    HCC_ESRD_V24      VARCHAR(10),
    HCC_V22           VARCHAR(10),
    HCC_V28           VARCHAR(10),
    RXHCC_V08         VARCHAR(10),
    RA_2026_ESRD_V21  BOOLEAN,
    RA_2026_ESRD_V24  BOOLEAN,
    RA_2026_V22       BOOLEAN,
    RA_2026_V28       BOOLEAN,
    RA_2026_RXHCC     BOOLEAN
);

CREATE TABLE IF NOT EXISTS ICD10_CODING_APP.ICD10_REF.ICD10_CODES (
    ICD10_CODE        VARCHAR,
    SHORT_DESCRIPTION VARCHAR,
    LONG_DESCRIPTION  VARCHAR,
    CATEGORY_CODE     VARCHAR,
    CHAPTER           VARCHAR(26)
);

CREATE TABLE IF NOT EXISTS ICD10_CODING_APP.ICD10_REF.HCC_MAPPINGS (
    ICD10_CODE        VARCHAR,
    HCC_CATEGORY      NUMBER(3,0),
    HCC_DESCRIPTION   VARCHAR(72),
    RAF_COEFFICIENT   NUMBER(4,3)
);

-- =============================================================================
-- SECTION 3: Create a temporary stage and load data from parquet files
-- =============================================================================
-- Upload the data/ folder contents to this stage BEFORE running COPY INTO.
-- From a Snowsight worksheet, you can use:
--   PUT file:///path/to/data/*.parquet @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE AUTO_COMPRESS=FALSE;
-- Or from SnowCLI:
--   snow stage copy data/ @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE --overwrite

CREATE STAGE IF NOT EXISTS CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE;

-- ** PAUSE HERE ** —  upload parquet files to the stage before continuing.
-- You can run this in a Snowsight Python cell or from the CLI:
--
--   PUT file:///workspace/experiments_v2_package/data/encounters_*.snappy.parquet
--       @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/encounters/ AUTO_COMPRESS=FALSE;
--   PUT file:///workspace/experiments_v2_package/data/ground_truth_*.snappy.parquet
--       @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/ground_truth/ AUTO_COMPRESS=FALSE;
--   PUT file:///workspace/experiments_v2_package/data/icd10_hcc_mappings_*.snappy.parquet
--       @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/icd10_hcc_mappings/ AUTO_COMPRESS=FALSE;
--   PUT file:///workspace/experiments_v2_package/data/icd10_codes_*.snappy.parquet
--       @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/icd10_codes/ AUTO_COMPRESS=FALSE;
--   PUT file:///workspace/experiments_v2_package/data/hcc_mappings_*.snappy.parquet
--       @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/hcc_mappings/ AUTO_COMPRESS=FALSE;

-- =============================================================================
-- SECTION 4: Load data from stage into tables
-- =============================================================================

-- Encounters (VARIANT columns were exported as VARCHAR — parse them back)
COPY INTO CHART_REVIEW_DB.RAW.ENCOUNTERS
    (ENCOUNTER_ID, SOURCE_FILE, ENCOUNTER_SEQ, SERVICE_START_DATE, SERVICE_END_DATE,
     CCD_STATUS, MEMBER_ID, MEMBER_FIRST, MEMBER_LAST, MEMBER_DOB, MEMBER_GENDER,
     MEMBER_ADDRESS, MEMBER_CITY, MEMBER_STATE, MEMBER_ZIP, OID, PROVIDER_TIN,
     SOURCE_SYSTEM, CDR_LOAD_DATE,
     DIAGNOSIS_CODES, NARRATIVES, PERFORMERS, RAW_RECORD,
     LOADED_AT, BATCH)
FROM (
    SELECT
        $1:ENCOUNTER_ID::VARCHAR,
        $1:SOURCE_FILE::VARCHAR,
        $1:ENCOUNTER_SEQ::VARCHAR,
        $1:SERVICE_START_DATE::TIMESTAMP_NTZ,
        $1:SERVICE_END_DATE::TIMESTAMP_NTZ,
        $1:CCD_STATUS::VARCHAR,
        $1:MEMBER_ID::VARCHAR,
        $1:MEMBER_FIRST::VARCHAR,
        $1:MEMBER_LAST::VARCHAR,
        $1:MEMBER_DOB::DATE,
        $1:MEMBER_GENDER::VARCHAR,
        $1:MEMBER_ADDRESS::VARCHAR,
        $1:MEMBER_CITY::VARCHAR,
        $1:MEMBER_STATE::VARCHAR,
        $1:MEMBER_ZIP::VARCHAR,
        $1:OID::VARCHAR,
        $1:PROVIDER_TIN::VARCHAR,
        $1:SOURCE_SYSTEM::VARCHAR,
        $1:CDR_LOAD_DATE::TIMESTAMP_NTZ,
        TRY_PARSE_JSON($1:DIAGNOSIS_CODES::VARCHAR),
        TRY_PARSE_JSON($1:NARRATIVES::VARCHAR),
        TRY_PARSE_JSON($1:PERFORMERS::VARCHAR),
        TRY_PARSE_JSON($1:RAW_RECORD::VARCHAR),
        $1:LOADED_AT::TIMESTAMP_NTZ,
        $1:BATCH::VARCHAR
    FROM @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/encounters/
)
FILE_FORMAT = (TYPE = PARQUET)
MATCH_BY_COLUMN_NAME = NONE;

COPY INTO CHART_REVIEW_DB.RAW.AETNA_GROUND_TRUTH
FROM @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/ground_truth/
FILE_FORMAT = (TYPE = PARQUET)
MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

COPY INTO CHART_REVIEW_DB.RAW.ICD10_HCC_MAPPINGS
FROM @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/icd10_hcc_mappings/
FILE_FORMAT = (TYPE = PARQUET)
MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

COPY INTO ICD10_CODING_APP.ICD10_REF.ICD10_CODES
FROM @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/icd10_codes/
FILE_FORMAT = (TYPE = PARQUET)
MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

COPY INTO ICD10_CODING_APP.ICD10_REF.HCC_MAPPINGS
FROM @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/hcc_mappings/
FILE_FORMAT = (TYPE = PARQUET)
MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

-- =============================================================================
-- SECTION 5: Verify loaded data
-- =============================================================================

SELECT 'ENCOUNTERS'        AS TABLE_NAME, COUNT(*) AS ROW_COUNT FROM CHART_REVIEW_DB.RAW.ENCOUNTERS
UNION ALL SELECT 'AETNA_GROUND_TRUTH',  COUNT(*) FROM CHART_REVIEW_DB.RAW.AETNA_GROUND_TRUTH
UNION ALL SELECT 'ICD10_HCC_MAPPINGS',  COUNT(*) FROM CHART_REVIEW_DB.RAW.ICD10_HCC_MAPPINGS
UNION ALL SELECT 'ICD10_CODES',         COUNT(*) FROM ICD10_CODING_APP.ICD10_REF.ICD10_CODES
UNION ALL SELECT 'HCC_MAPPINGS',        COUNT(*) FROM ICD10_CODING_APP.ICD10_REF.HCC_MAPPINGS;

-- Expected counts:
--   ENCOUNTERS:        1,340
--   AETNA_GROUND_TRUTH: 2,275
--   ICD10_HCC_MAPPINGS: 11,866
--   ICD10_CODES:        74,260
--   HCC_MAPPINGS:       20,500

-- =============================================================================
-- SECTION 6: Create experiment tracking tables (used by notebook 04/05)
-- =============================================================================

CREATE TABLE IF NOT EXISTS ICD10_CODING_APP.EXPERIMENTS.RUNS (
    RUN_ID           VARCHAR,
    RUN_NAME         VARCHAR,
    STARTED_AT       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPLETED_AT     TIMESTAMP_NTZ,
    STATUS           VARCHAR DEFAULT 'RUNNING',
    EXTRACTION_MODEL VARCHAR,
    MATCHING_MODEL   VARCHAR,
    EVAL_MODEL       VARCHAR,
    PARAMETERS       VARIANT,
    NOTES            VARCHAR
);

CREATE TABLE IF NOT EXISTS ICD10_CODING_APP.EXPERIMENTS.METRICS (
    RUN_ID      VARCHAR,
    METRIC_NAME VARCHAR,
    METRIC_VALUE FLOAT,
    DETAILS     VARIANT,
    LOGGED_AT   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- =============================================================================
-- DONE! Now run the notebooks in order:
--   1. 00_setup.ipynb      — creates DOCUMENT_SECTIONS, enriched ICD-10 corpus, dual-code pairs
--   2. 01_extraction.ipynb  — LLM extraction of clinical findings
--   3. 02_search.ipynb      — multi-path ICD-10 candidate retrieval
--   4. 03_matching.ipynb    — LLM code assignment
--   5. 04_evaluation.ipynb  — evaluate against ground truth
--   6. 05_run_experiment.ipynb — (optional) consolidated end-to-end runner
-- =============================================================================
