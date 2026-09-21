# Automated setup for ICD-10 Coding Pipeline
# Co-authored with CoCo
#
# Run this in a Snowflake notebook Python cell or as a .py file in a workspace.
# It will execute setup.sql step by step, upload data, and verify.

import os

def run_setup(session, data_dir="/workspace/experiments_v2_package/data"):
    """
    Full automated setup. Pass in an active Snowpark session.
    data_dir should point to the folder containing the parquet files.
    """
    print("=" * 60)
    print("ICD-10 Coding Pipeline — Automated Setup")
    print("=" * 60)

    # Step 1: Databases and schemas
    print("\n[1/6] Creating databases and schemas...")
    for stmt in [
        "CREATE DATABASE IF NOT EXISTS CHART_REVIEW_DB",
        "CREATE SCHEMA IF NOT EXISTS CHART_REVIEW_DB.RAW",
        "CREATE DATABASE IF NOT EXISTS ICD10_CODING_APP",
        "CREATE SCHEMA IF NOT EXISTS ICD10_CODING_APP.PROCESSING",
        "CREATE SCHEMA IF NOT EXISTS ICD10_CODING_APP.MATCHING",
        "CREATE SCHEMA IF NOT EXISTS ICD10_CODING_APP.EXPERIMENTS",
        "CREATE SCHEMA IF NOT EXISTS ICD10_CODING_APP.ICD10_REF",
    ]:
        session.sql(stmt).collect()
    print("  Done.")

    # Step 2: Create tables
    print("\n[2/6] Creating tables...")

    session.sql("""
        CREATE TABLE IF NOT EXISTS CHART_REVIEW_DB.RAW.ENCOUNTERS (
            ENCOUNTER_ID VARCHAR(50) DEFAULT UUID_STRING(), SOURCE_FILE VARCHAR(200),
            ENCOUNTER_SEQ VARCHAR(50), SERVICE_START_DATE TIMESTAMP_NTZ,
            SERVICE_END_DATE TIMESTAMP_NTZ, CCD_STATUS VARCHAR(20),
            MEMBER_ID VARCHAR(50), MEMBER_FIRST VARCHAR(100), MEMBER_LAST VARCHAR(100),
            MEMBER_DOB DATE, MEMBER_GENDER VARCHAR(20), MEMBER_ADDRESS VARCHAR(200),
            MEMBER_CITY VARCHAR(100), MEMBER_STATE VARCHAR(5), MEMBER_ZIP VARCHAR(10),
            OID VARCHAR(200), PROVIDER_TIN VARCHAR(50), SOURCE_SYSTEM VARCHAR(50),
            CDR_LOAD_DATE TIMESTAMP_NTZ, DIAGNOSIS_CODES VARIANT, NARRATIVES VARIANT,
            PERFORMERS VARIANT, RAW_RECORD VARIANT,
            LOADED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(), BATCH VARCHAR
        )
    """).collect()

    session.sql("""
        CREATE TABLE IF NOT EXISTS CHART_REVIEW_DB.RAW.AETNA_GROUND_TRUTH (
            CHASE_ID VARCHAR, DIAGNOSIS_CODE VARCHAR, ICD_CODE_DISPOSITION VARCHAR,
            DISPOSITION_REASON VARCHAR, DOS_START_DATE DATE, DOS_END_DATE DATE,
            BATCH VARCHAR DEFAULT 'BATCH_01',
            LOADED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """).collect()

    session.sql("""
        CREATE TABLE IF NOT EXISTS CHART_REVIEW_DB.RAW.ICD10_HCC_MAPPINGS (
            ICD_CODE VARCHAR(10), DESCRIPTION VARCHAR(500),
            HCC_ESRD_V21 VARCHAR(10), HCC_ESRD_V24 VARCHAR(10),
            HCC_V22 VARCHAR(10), HCC_V28 VARCHAR(10), RXHCC_V08 VARCHAR(10),
            RA_2026_ESRD_V21 BOOLEAN, RA_2026_ESRD_V24 BOOLEAN,
            RA_2026_V22 BOOLEAN, RA_2026_V28 BOOLEAN, RA_2026_RXHCC BOOLEAN
        )
    """).collect()

    session.sql("""
        CREATE TABLE IF NOT EXISTS ICD10_CODING_APP.ICD10_REF.ICD10_CODES (
            ICD10_CODE VARCHAR, SHORT_DESCRIPTION VARCHAR, LONG_DESCRIPTION VARCHAR,
            CATEGORY_CODE VARCHAR, CHAPTER VARCHAR(26)
        )
    """).collect()

    session.sql("""
        CREATE TABLE IF NOT EXISTS ICD10_CODING_APP.ICD10_REF.HCC_MAPPINGS (
            ICD10_CODE VARCHAR, HCC_CATEGORY NUMBER(3,0),
            HCC_DESCRIPTION VARCHAR(72), RAF_COEFFICIENT NUMBER(4,3)
        )
    """).collect()

    session.sql("""
        CREATE TABLE IF NOT EXISTS ICD10_CODING_APP.EXPERIMENTS.RUNS (
            RUN_ID VARCHAR, RUN_NAME VARCHAR,
            STARTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
            COMPLETED_AT TIMESTAMP_NTZ, STATUS VARCHAR DEFAULT 'RUNNING',
            EXTRACTION_MODEL VARCHAR, MATCHING_MODEL VARCHAR, EVAL_MODEL VARCHAR,
            PARAMETERS VARIANT, NOTES VARCHAR
        )
    """).collect()

    session.sql("""
        CREATE TABLE IF NOT EXISTS ICD10_CODING_APP.EXPERIMENTS.METRICS (
            RUN_ID VARCHAR, METRIC_NAME VARCHAR, METRIC_VALUE FLOAT,
            DETAILS VARIANT, LOGGED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """).collect()
    print("  Done.")

    # Step 3: Create stage and upload data
    print("\n[3/6] Creating stage...")
    session.sql("CREATE STAGE IF NOT EXISTS CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE").collect()
    print("  Done.")

    print("\n[4/6] Uploading parquet files to stage...")
    uploads = {
        "encounters": "encounters_*.snappy.parquet",
        "ground_truth": "ground_truth_*.snappy.parquet",
        "icd10_hcc_mappings": "icd10_hcc_mappings_*.snappy.parquet",
        "icd10_codes": "icd10_codes_*.snappy.parquet",
        "hcc_mappings": "hcc_mappings_*.snappy.parquet",
    }
    for folder, pattern in uploads.items():
        put_cmd = (
            f"PUT file://{data_dir}/{pattern} "
            f"@CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/{folder}/ "
            f"AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
        )
        result = session.sql(put_cmd).collect()
        print(f"  {folder}: {len(result)} file(s) uploaded")
    print("  Done.")

    # Step 4: Load data
    print("\n[5/6] Loading data into tables...")

    session.sql("""
        COPY INTO CHART_REVIEW_DB.RAW.ENCOUNTERS
            (ENCOUNTER_ID, SOURCE_FILE, ENCOUNTER_SEQ, SERVICE_START_DATE, SERVICE_END_DATE,
             CCD_STATUS, MEMBER_ID, MEMBER_FIRST, MEMBER_LAST, MEMBER_DOB, MEMBER_GENDER,
             MEMBER_ADDRESS, MEMBER_CITY, MEMBER_STATE, MEMBER_ZIP, OID, PROVIDER_TIN,
             SOURCE_SYSTEM, CDR_LOAD_DATE, DIAGNOSIS_CODES, NARRATIVES, PERFORMERS, RAW_RECORD,
             LOADED_AT, BATCH)
        FROM (
            SELECT $1:ENCOUNTER_ID::VARCHAR, $1:SOURCE_FILE::VARCHAR, $1:ENCOUNTER_SEQ::VARCHAR,
                   $1:SERVICE_START_DATE::TIMESTAMP_NTZ, $1:SERVICE_END_DATE::TIMESTAMP_NTZ,
                   $1:CCD_STATUS::VARCHAR, $1:MEMBER_ID::VARCHAR, $1:MEMBER_FIRST::VARCHAR,
                   $1:MEMBER_LAST::VARCHAR, $1:MEMBER_DOB::DATE, $1:MEMBER_GENDER::VARCHAR,
                   $1:MEMBER_ADDRESS::VARCHAR, $1:MEMBER_CITY::VARCHAR, $1:MEMBER_STATE::VARCHAR,
                   $1:MEMBER_ZIP::VARCHAR, $1:OID::VARCHAR, $1:PROVIDER_TIN::VARCHAR,
                   $1:SOURCE_SYSTEM::VARCHAR, $1:CDR_LOAD_DATE::TIMESTAMP_NTZ,
                   TRY_PARSE_JSON($1:DIAGNOSIS_CODES::VARCHAR),
                   TRY_PARSE_JSON($1:NARRATIVES::VARCHAR),
                   TRY_PARSE_JSON($1:PERFORMERS::VARCHAR),
                   TRY_PARSE_JSON($1:RAW_RECORD::VARCHAR),
                   $1:LOADED_AT::TIMESTAMP_NTZ, $1:BATCH::VARCHAR
            FROM @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/encounters/
        )
        FILE_FORMAT = (TYPE = PARQUET) MATCH_BY_COLUMN_NAME = NONE
    """).collect()
    print("  encounters loaded")

    for tbl, path in [
        ("CHART_REVIEW_DB.RAW.AETNA_GROUND_TRUTH", "ground_truth"),
        ("CHART_REVIEW_DB.RAW.ICD10_HCC_MAPPINGS", "icd10_hcc_mappings"),
        ("ICD10_CODING_APP.ICD10_REF.ICD10_CODES", "icd10_codes"),
        ("ICD10_CODING_APP.ICD10_REF.HCC_MAPPINGS", "hcc_mappings"),
    ]:
        session.sql(f"""
            COPY INTO {tbl}
            FROM @CHART_REVIEW_DB.RAW.DATA_LOAD_STAGE/{path}/
            FILE_FORMAT = (TYPE = PARQUET)
            MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
        """).collect()
        print(f"  {tbl.split('.')[-1].lower()} loaded")
    print("  Done.")

    # Step 5: Verify
    print("\n[6/6] Verifying row counts...")
    expected = {
        "ENCOUNTERS": 1340,
        "AETNA_GROUND_TRUTH": 2275,
        "ICD10_HCC_MAPPINGS": 11866,
        "ICD10_CODES": 74260,
        "HCC_MAPPINGS": 20500,
    }
    results = session.sql("""
        SELECT 'ENCOUNTERS' AS T, COUNT(*) AS N FROM CHART_REVIEW_DB.RAW.ENCOUNTERS
        UNION ALL SELECT 'AETNA_GROUND_TRUTH', COUNT(*) FROM CHART_REVIEW_DB.RAW.AETNA_GROUND_TRUTH
        UNION ALL SELECT 'ICD10_HCC_MAPPINGS', COUNT(*) FROM CHART_REVIEW_DB.RAW.ICD10_HCC_MAPPINGS
        UNION ALL SELECT 'ICD10_CODES', COUNT(*) FROM ICD10_CODING_APP.ICD10_REF.ICD10_CODES
        UNION ALL SELECT 'HCC_MAPPINGS', COUNT(*) FROM ICD10_CODING_APP.ICD10_REF.HCC_MAPPINGS
    """).collect()

    all_ok = True
    for row in results:
        name, count = row[0], row[1]
        exp = expected.get(name, "?")
        status = "OK" if count == exp else f"MISMATCH (expected {exp})"
        if count != exp:
            all_ok = False
        print(f"  {name}: {count:,} rows — {status}")

    print("\n" + "=" * 60)
    if all_ok:
        print("Setup complete! All tables loaded successfully.")
        print("\nNext steps:")
        print("  1. Run 00_setup.ipynb (creates derived tables & UDFs)")
        print("  2. Run 01_extraction.ipynb through 04_evaluation.ipynb in order")
        print("  3. Or use 05_run_experiment.ipynb for an all-in-one run")
    else:
        print("WARNING: Some tables have unexpected row counts.")
        print("Check the COPY INTO results above for errors.")
    print("=" * 60)


if __name__ == "__main__":
    from snowflake.snowpark import Session
    session = Session.builder.getOrCreate()
    run_setup(session)
