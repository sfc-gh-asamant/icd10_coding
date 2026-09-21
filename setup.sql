-- =============================================================================
-- ICD-10 Retrieval-Grounded Coding Pipeline — Snowflake Setup
-- =============================================================================
-- This script creates all database objects needed by the app.
--
-- BEFORE RUNNING: Find-and-replace these placeholders with your values:
--   {{DATABASE}}    → your database name   (e.g. ICD10_CODING_DB)
--   {{WAREHOUSE}}   → your warehouse name  (e.g. COMPUTE_WH)
--
-- Requirements:
--   - ACCOUNTADMIN or a role with CREATE DATABASE, CREATE CORTEX SEARCH SERVICE
--   - Cortex AI functions enabled on your account
--   - A warehouse for Cortex Search indexing
-- =============================================================================

-- 1. Database & schemas
CREATE DATABASE IF NOT EXISTS {{DATABASE}};
CREATE SCHEMA IF NOT EXISTS {{DATABASE}}.RAW;
CREATE SCHEMA IF NOT EXISTS {{DATABASE}}.HARMONIZED;

USE SCHEMA {{DATABASE}}.RAW;

-- 2. Stages
CREATE STAGE IF NOT EXISTS ENCOUNTER_STAGE
    DIRECTORY = (ENABLE = TRUE)
    COMMENT = 'Landing zone for encounter JSONL files';

-- 3. Core tables
CREATE TABLE IF NOT EXISTS ENCOUNTERS (
    ENCOUNTER_ID       VARCHAR(50) DEFAULT UUID_STRING(),
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
) COMMENT = 'Structured encounter data ingested from JSONL files';

CREATE TABLE IF NOT EXISTS ICD10_HCC_MAPPINGS (
    ICD_CODE           VARCHAR(10),
    DESCRIPTION        VARCHAR(500),
    HCC_ESRD_V21       VARCHAR(10),
    HCC_ESRD_V24       VARCHAR(10),
    HCC_V22            VARCHAR(10),
    HCC_V28            VARCHAR(10),
    RXHCC_V08          VARCHAR(10),
    RA_2026_ESRD_V21   BOOLEAN,
    RA_2026_ESRD_V24   BOOLEAN,
    RA_2026_V22        BOOLEAN,
    RA_2026_V28        BOOLEAN,
    RA_2026_RXHCC      BOOLEAN
) COMMENT = '2026 ICD-10-CM to HCC mappings. Source: CMS FY2026 final mappings.';

CREATE TABLE IF NOT EXISTS ENCOUNTER_DIAGNOSES (
    DIAGNOSIS_ID          VARCHAR(50) DEFAULT UUID_STRING(),
    ENCOUNTER_ID          VARCHAR(50),
    DIAGNOSIS_TEXT         VARCHAR(1000),
    EVIDENCE              VARCHAR(2000),
    CONFIDENCE            FLOAT,
    SOURCE_NARRATIVE_TYPE VARCHAR(50),
    EXTRACTED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
) COMMENT = 'AI-extracted diagnoses from encounter narratives';

CREATE TABLE IF NOT EXISTS ENCOUNTER_DX_CANDIDATES (
    CANDIDATE_ID   VARCHAR(50) DEFAULT UUID_STRING(),
    DIAGNOSIS_ID   VARCHAR(50),
    ENCOUNTER_ID   VARCHAR(50),
    SEARCH_RANK    NUMBER,
    ICD_CODE       VARCHAR(10),
    ICD_DESCRIPTION VARCHAR(500),
    HCC_V28        VARCHAR(10),
    RA_2026_V28    BOOLEAN,
    SEARCH_SCORE   FLOAT,
    RETRIEVED_AT   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
) COMMENT = 'Top-10 candidate ICD codes per extracted diagnosis (from Cortex Search)';

CREATE TABLE IF NOT EXISTS ENCOUNTER_ICD_CODES_ASSIGNED (
    ASSIGNMENT_ID        VARCHAR(50) DEFAULT UUID_STRING(),
    DIAGNOSIS_ID         VARCHAR(50),
    ENCOUNTER_ID         VARCHAR(50),
    ASSIGNED_ICD_CODE    VARCHAR(10),
    ASSIGNED_DESCRIPTION VARCHAR(500),
    HCC_V28              VARCHAR(10),
    RA_2026_V28          BOOLEAN,
    RATIONALE            VARCHAR(1000),
    CONFIDENCE           FLOAT,
    ASSIGNED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
) COMMENT = 'AI-assigned best-fit ICD code per diagnosis (grounded, no hallucination)';

CREATE TABLE IF NOT EXISTS CODE_REVIEW_DECISIONS (
    DECISION_ID    VARCHAR(50) DEFAULT UUID_STRING(),
    ASSIGNMENT_ID  VARCHAR(50),
    ENCOUNTER_ID   VARCHAR(50),
    ICD_CODE       VARCHAR(10),
    DECISION       VARCHAR(20),
    REVIEWER_NAME  VARCHAR(200),
    NOTES          VARCHAR,
    DECIDED_AT     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- 4. Stream (append-only on ENCOUNTERS for auto-pipeline)
CREATE STREAM IF NOT EXISTS ENCOUNTERS_STREAM
    ON TABLE ENCOUNTERS
    APPEND_ONLY = TRUE
    COMMENT = 'Detects new encounters for pipeline processing';

-- 5. Cortex Search service over ICD-10 reference codes
CREATE OR REPLACE CORTEX SEARCH SERVICE ICD10_SEARCH_SVC
    ON (
        SELECT
            ICD_CODE,
            DESCRIPTION,
            HCC_V28,
            HCC_ESRD_V24,
            RA_2026_V28,
            RA_2026_ESRD_V24,
            ICD_CODE || ' - ' || DESCRIPTION AS SEARCH_TEXT
        FROM {{DATABASE}}.RAW.ICD10_HCC_MAPPINGS
    )
    WAREHOUSE = {{WAREHOUSE}}
    TARGET_LAG = '1 day'
    EMBEDDING_MODEL = 'snowflake-arctic-embed-m-v1.5'
    SEARCH_COLUMN = SEARCH_TEXT
    ATTRIBUTE_COLUMNS = ICD_CODE, DESCRIPTION, HCC_V28, HCC_ESRD_V24, RA_2026_V28, RA_2026_ESRD_V24;

-- 6. Stored procedures

-- Step 1: Extract diagnoses from narratives using AI_COMPLETE
CREATE OR REPLACE PROCEDURE SP_EXTRACT_DIAGNOSES(ENCOUNTER_ID_FILTER VARCHAR DEFAULT NULL)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
'
BEGIN
    INSERT INTO {{DATABASE}}.RAW.ENCOUNTER_DIAGNOSES (ENCOUNTER_ID, DIAGNOSIS_TEXT, EVIDENCE, CONFIDENCE, SOURCE_NARRATIVE_TYPE)
    WITH encounters_to_process AS (
        SELECT e.ENCOUNTER_ID, n.VALUE:Type::VARCHAR AS NARR_TYPE, n.VALUE:Value::VARCHAR AS NARR_TEXT
        FROM {{DATABASE}}.RAW.ENCOUNTERS e,
             LATERAL FLATTEN(INPUT => e.NARRATIVES) n
        WHERE (:ENCOUNTER_ID_FILTER IS NULL OR e.ENCOUNTER_ID = :ENCOUNTER_ID_FILTER)
        AND e.ENCOUNTER_ID NOT IN (SELECT DISTINCT ENCOUNTER_ID FROM {{DATABASE}}.RAW.ENCOUNTER_DIAGNOSES)
    ),
    extracted AS (
        SELECT
            ENCOUNTER_ID,
            NARR_TYPE,
            REGEXP_REPLACE(
                SNOWFLAKE.CORTEX.COMPLETE(''claude-sonnet-4-6'',
                    ''You are a clinical coder. Extract all medical diagnoses from this clinical note. ''
                    || ''Return a JSON array where each element has: ''
                    || ''{"diagnosis": "condition name", "evidence": "brief quote from text", "confidence": 0.0-1.0}. ''
                    || ''Only return the JSON array, no other text. If no diagnoses found, return []. ''
                    || ''Clinical note: '' || REGEXP_REPLACE(NARR_TEXT, ''<[^>]+>'', '' '')
                ),
                ''```json|```'', ''''
            ) AS AI_RESPONSE
        FROM encounters_to_process
        WHERE NARR_TEXT IS NOT NULL AND LENGTH(NARR_TEXT) > 50
    )
    SELECT
        e.ENCOUNTER_ID,
        dx.VALUE:diagnosis::VARCHAR AS DIAGNOSIS_TEXT,
        dx.VALUE:evidence::VARCHAR AS EVIDENCE,
        dx.VALUE:confidence::FLOAT AS CONFIDENCE,
        e.NARR_TYPE AS SOURCE_NARRATIVE_TYPE
    FROM extracted e,
         LATERAL FLATTEN(INPUT => TRY_PARSE_JSON(TRIM(e.AI_RESPONSE))) dx
    WHERE dx.VALUE:diagnosis IS NOT NULL;

    RETURN ''Diagnoses extracted successfully'';
END;
';

-- Step 2: Retrieve candidate ICD codes via Cortex Search
CREATE OR REPLACE PROCEDURE SP_RETRIEVE_CANDIDATES(ENCOUNTER_ID_FILTER VARCHAR DEFAULT NULL)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
EXECUTE AS CALLER
AS
'
import json

def run(session, encounter_id_filter):
    filter_clause = ""
    if encounter_id_filter:
        filter_clause = f"AND ENCOUNTER_ID = ''{encounter_id_filter}''"

    diagnoses = session.sql(f"""
        SELECT DIAGNOSIS_ID, ENCOUNTER_ID, DIAGNOSIS_TEXT
        FROM {{DATABASE}}.RAW.ENCOUNTER_DIAGNOSES
        WHERE DIAGNOSIS_ID NOT IN (SELECT DISTINCT DIAGNOSIS_ID FROM {{DATABASE}}.RAW.ENCOUNTER_DX_CANDIDATES)
        {filter_clause}
    """).collect()

    if not diagnoses:
        return "No new diagnoses to search"

    rows_inserted = 0
    for row in diagnoses:
        diag_id = row["DIAGNOSIS_ID"]
        enc_id = row["ENCOUNTER_ID"]
        diag_text = row["DIAGNOSIS_TEXT"].replace("''", "''''")

        try:
            result = session.sql(f"""
                SELECT PARSE_JSON(
                    SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
                        ''{{DATABASE}}.RAW.ICD10_SEARCH_SVC'',
                        ''{{"query": "{diag_text}", "columns": ["ICD_CODE", "DESCRIPTION", "HCC_V28", "RA_2026_V28"], "limit": 10}}''
                    )
                ) AS RESULT
            """).collect()

            if not result:
                continue

            search_result = json.loads(result[0]["RESULT"])
            result_list = search_result.get("results", [])

            for rank, item in enumerate(result_list, 1):
                icd_code = item.get("ICD_CODE", "")
                description = item.get("DESCRIPTION", "").replace("''", "''''")
                hcc_v28 = item.get("HCC_V28", "")
                ra_v28 = str(item.get("RA_2026_V28", "false")).lower() == "true"
                scores = item.get("@scores", {})
                score = scores.get("cosine_similarity", 0.0)

                session.sql(f"""
                    INSERT INTO {{DATABASE}}.RAW.ENCOUNTER_DX_CANDIDATES
                    (DIAGNOSIS_ID, ENCOUNTER_ID, SEARCH_RANK, ICD_CODE, ICD_DESCRIPTION, HCC_V28, RA_2026_V28, SEARCH_SCORE)
                    VALUES (''{diag_id}'', ''{enc_id}'', {rank}, ''{icd_code}'', ''{description}'',
                            ''{hcc_v28}'', {ra_v28}, {score})
                """).collect()
                rows_inserted += 1
        except Exception as e:
            continue

    return f"Candidates retrieved: {rows_inserted} rows for {len(diagnoses)} diagnoses"
';

-- Step 3: Assign best-fit ICD code from candidate set
CREATE OR REPLACE PROCEDURE SP_ASSIGN_ICD_CODES(ENCOUNTER_ID_FILTER VARCHAR DEFAULT NULL)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
'
BEGIN
    INSERT INTO {{DATABASE}}.RAW.ENCOUNTER_ICD_CODES_ASSIGNED
        (DIAGNOSIS_ID, ENCOUNTER_ID, ASSIGNED_ICD_CODE, ASSIGNED_DESCRIPTION, HCC_V28, RA_2026_V28, RATIONALE, CONFIDENCE)
    WITH diagnoses_with_candidates AS (
        SELECT
            d.DIAGNOSIS_ID,
            d.ENCOUNTER_ID,
            d.DIAGNOSIS_TEXT,
            d.EVIDENCE,
            ARRAY_AGG(
                OBJECT_CONSTRUCT(''code'', c.ICD_CODE, ''description'', c.ICD_DESCRIPTION, ''hcc'', c.HCC_V28, ''ra'', c.RA_2026_V28)
            ) WITHIN GROUP (ORDER BY c.SEARCH_RANK) AS CANDIDATES
        FROM {{DATABASE}}.RAW.ENCOUNTER_DIAGNOSES d
        JOIN {{DATABASE}}.RAW.ENCOUNTER_DX_CANDIDATES c ON d.DIAGNOSIS_ID = c.DIAGNOSIS_ID
        WHERE (:ENCOUNTER_ID_FILTER IS NULL OR d.ENCOUNTER_ID = :ENCOUNTER_ID_FILTER)
        AND d.DIAGNOSIS_ID NOT IN (SELECT DISTINCT DIAGNOSIS_ID FROM {{DATABASE}}.RAW.ENCOUNTER_ICD_CODES_ASSIGNED)
        GROUP BY d.DIAGNOSIS_ID, d.ENCOUNTER_ID, d.DIAGNOSIS_TEXT, d.EVIDENCE
    ),
    assigned AS (
        SELECT
            DIAGNOSIS_ID,
            ENCOUNTER_ID,
            REGEXP_REPLACE(
                SNOWFLAKE.CORTEX.COMPLETE(''claude-sonnet-4-6'',
                    ''You are a clinical ICD-10 coder. Given a diagnosis extracted from a clinical note and a list of candidate ICD-10-CM codes, ''
                    || ''select the SINGLE best-fit code. You MUST pick from the candidate list only. ''
                    || ''Return JSON: {"code": "X99.9", "description": "...", "rationale": "why this code fits", "confidence": 0.0-1.0}. ''
                    || ''Only return the JSON object. ''
                    || ''Diagnosis: '' || DIAGNOSIS_TEXT
                    || CASE WHEN EVIDENCE IS NOT NULL THEN '' | Evidence: '' || EVIDENCE ELSE '''' END
                    || '' | Candidates: '' || CANDIDATES::VARCHAR
                ),
                ''```json|```'', ''''
            ) AS AI_RESPONSE
        FROM diagnoses_with_candidates
    )
    SELECT
        a.DIAGNOSIS_ID,
        a.ENCOUNTER_ID,
        TRY_PARSE_JSON(TRIM(a.AI_RESPONSE)):code::VARCHAR AS ASSIGNED_ICD_CODE,
        TRY_PARSE_JSON(TRIM(a.AI_RESPONSE)):description::VARCHAR AS ASSIGNED_DESCRIPTION,
        m.HCC_V28,
        m.RA_2026_V28,
        TRY_PARSE_JSON(TRIM(a.AI_RESPONSE)):rationale::VARCHAR AS RATIONALE,
        TRY_PARSE_JSON(TRIM(a.AI_RESPONSE)):confidence::FLOAT AS CONFIDENCE
    FROM assigned a
    LEFT JOIN {{DATABASE}}.RAW.ICD10_HCC_MAPPINGS m
        ON REPLACE(TRY_PARSE_JSON(TRIM(a.AI_RESPONSE)):code::VARCHAR, ''.'', '''') = REPLACE(m.ICD_CODE, ''.'', '''')
    WHERE TRY_PARSE_JSON(TRIM(a.AI_RESPONSE)):code IS NOT NULL;

    RETURN ''ICD codes assigned successfully'';
END;
';

-- 7. Views (HARMONIZED schema)
USE SCHEMA {{DATABASE}}.HARMONIZED;

CREATE OR REPLACE VIEW ENCOUNTER_QUALITY AS
SELECT
    ENCOUNTER_ID, SOURCE_FILE, ENCOUNTER_SEQ, MEMBER_ID,
    MEMBER_FIRST, MEMBER_LAST, MEMBER_DOB, MEMBER_GENDER, SERVICE_START_DATE,
    (MEMBER_DOB IS NOT NULL)::INT AS HAS_DOB,
    (MEMBER_FIRST IS NOT NULL)::INT AS HAS_FIRST_NAME,
    (MEMBER_LAST IS NOT NULL)::INT AS HAS_LAST_NAME,
    (MEMBER_GENDER IS NOT NULL)::INT AS HAS_GENDER,
    (MEMBER_ID IS NOT NULL)::INT AS HAS_MEMBER_ID,
    (SERVICE_START_DATE IS NOT NULL)::INT AS HAS_SERVICE_DATE,
    (ARRAY_SIZE(DIAGNOSIS_CODES) > 0)::INT AS HAS_DIAGNOSIS_CODES,
    (ARRAY_SIZE(NARRATIVES) > 0)::INT AS HAS_NARRATIVES,
    ROUND((
        (MEMBER_DOB IS NOT NULL)::INT + (MEMBER_FIRST IS NOT NULL)::INT +
        (MEMBER_LAST IS NOT NULL)::INT + (MEMBER_GENDER IS NOT NULL)::INT +
        (MEMBER_ID IS NOT NULL)::INT + (SERVICE_START_DATE IS NOT NULL)::INT +
        (ARRAY_SIZE(DIAGNOSIS_CODES) > 0)::INT + (ARRAY_SIZE(NARRATIVES) > 0)::INT
    ) * 100.0 / 8, 1) AS QUALITY_SCORE,
    CASE
        WHEN (MEMBER_DOB IS NOT NULL) AND (MEMBER_FIRST IS NOT NULL) AND (MEMBER_LAST IS NOT NULL)
        THEN 'GOOD' ELSE 'BAD'
    END AS QUALITY_CLASSIFICATION,
    ARRAY_CONSTRUCT_COMPACT(
        IFF(MEMBER_DOB IS NULL, 'DOB', NULL),
        IFF(MEMBER_FIRST IS NULL, 'FirstName', NULL),
        IFF(MEMBER_LAST IS NULL, 'LastName', NULL),
        IFF(MEMBER_GENDER IS NULL, 'Gender', NULL),
        IFF(MEMBER_ID IS NULL, 'MemberID', NULL),
        IFF(SERVICE_START_DATE IS NULL, 'ServiceDate', NULL)
    ) AS MISSING_FIELDS
FROM {{DATABASE}}.RAW.ENCOUNTERS;

CREATE OR REPLACE VIEW VW_ENCOUNTER_ICD_CODING AS
WITH original_codes AS (
    SELECT
        e.ENCOUNTER_ID,
        ARRAY_AGG(DISTINCT REPLACE(dc.VALUE:Code::VARCHAR, '.', '')) AS ORIG_ICD_CODES
    FROM {{DATABASE}}.RAW.ENCOUNTERS e,
         LATERAL FLATTEN(INPUT => e.DIAGNOSIS_CODES) dc
    WHERE dc.VALUE:Qualifier::VARCHAR = 'ICD10'
    GROUP BY e.ENCOUNTER_ID
)
SELECT
    e.MEMBER_ID, e.MEMBER_FIRST, e.MEMBER_LAST, e.MEMBER_DOB, e.SERVICE_START_DATE,
    e.ENCOUNTER_ID, d.DIAGNOSIS_ID, d.DIAGNOSIS_TEXT, d.EVIDENCE AS DX_EVIDENCE,
    d.CONFIDENCE AS DX_CONFIDENCE, d.SOURCE_NARRATIVE_TYPE,
    a.ASSIGNED_ICD_CODE, a.ASSIGNED_DESCRIPTION, a.HCC_V28, a.RA_2026_V28,
    a.RATIONALE, a.CONFIDENCE AS CODING_CONFIDENCE,
    CASE
        WHEN a.RA_2026_V28 = TRUE
        AND NOT ARRAY_CONTAINS(REPLACE(a.ASSIGNED_ICD_CODE, '.', '')::VARIANT, COALESCE(oc.ORIG_ICD_CODES, ARRAY_CONSTRUCT()))
        THEN TRUE ELSE FALSE
    END AS MISSED_REVENUE
FROM {{DATABASE}}.RAW.ENCOUNTERS e
JOIN {{DATABASE}}.RAW.ENCOUNTER_DIAGNOSES d ON e.ENCOUNTER_ID = d.ENCOUNTER_ID
JOIN {{DATABASE}}.RAW.ENCOUNTER_ICD_CODES_ASSIGNED a ON d.DIAGNOSIS_ID = a.DIAGNOSIS_ID
LEFT JOIN original_codes oc ON e.ENCOUNTER_ID = oc.ENCOUNTER_ID;

-- 8. Task DAG (auto-pipeline on new encounters)
USE SCHEMA {{DATABASE}}.RAW;

CREATE OR REPLACE TASK PIPELINE_EXTRACT
    WAREHOUSE = {{WAREHOUSE}}
    SCHEDULE = '1 MINUTE'
    WHEN SYSTEM$STREAM_HAS_DATA('{{DATABASE}}.RAW.ENCOUNTERS_STREAM')
    AS CALL {{DATABASE}}.RAW.SP_EXTRACT_DIAGNOSES(NULL);

CREATE OR REPLACE TASK PIPELINE_RETRIEVE
    WAREHOUSE = {{WAREHOUSE}}
    AFTER {{DATABASE}}.RAW.PIPELINE_EXTRACT
    AS CALL {{DATABASE}}.RAW.SP_RETRIEVE_CANDIDATES(NULL);

CREATE OR REPLACE TASK PIPELINE_ASSIGN
    WAREHOUSE = {{WAREHOUSE}}
    AFTER {{DATABASE}}.RAW.PIPELINE_RETRIEVE
    AS CALL {{DATABASE}}.RAW.SP_ASSIGN_ICD_CODES(NULL);

-- Start the task DAG
ALTER TASK PIPELINE_ASSIGN  RESUME;
ALTER TASK PIPELINE_RETRIEVE RESUME;
ALTER TASK PIPELINE_EXTRACT  RESUME;

-- =============================================================================
-- DONE. Next steps:
-- 1. Load ICD-10 reference data into ICD10_HCC_MAPPINGS (see README)
-- 2. Upload encounter JSONL files via the app or PUT to @ENCOUNTER_STAGE
-- 3. Run: streamlit run app.py
-- =============================================================================
