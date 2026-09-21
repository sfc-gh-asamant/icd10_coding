import streamlit as st
import pandas as pd
import json
import re
from datetime import datetime, timedelta

# =============================================================================
# CONFIG — Change these to match your Snowflake environment
# =============================================================================
DATABASE = "CHART_REVIEW_DB"
RAW_SCHEMA = "RAW"
HARMONIZED_SCHEMA = "HARMONIZED"
APP_TITLE = "HEDIS Optimizer"
APP_ICON = ":material/health_and_safety:"
BRAND_NAME = "ICD-10 Coding"
BRAND_SUBTITLE = "Retrieval-Grounded Pipeline"
BRAND_COLOR = "#29B5E8"         # primary accent
BRAND_COLOR_DARK = "#1B2A4A"    # darker accent

# Fully-qualified table/view helpers
def raw(obj):
    return f"{DATABASE}.{RAW_SCHEMA}.{obj}"

def harmonized(obj):
    return f"{DATABASE}.{HARMONIZED_SCHEMA}.{obj}"

# =============================================================================
# App setup
# =============================================================================
st.set_page_config(page_title=APP_TITLE, layout="wide", page_icon=APP_ICON)

st.markdown(f"""
<style>
    [data-testid="stSidebar"] {{
        background-color: #F5F5F5;
        border-right: 2px solid #E3E3E3;
    }}
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1 {{
        color: {BRAND_COLOR_DARK};
    }}
    [data-testid="stMetric"] {{
        background-color: #FFFFFF;
        border: 1px solid #E3E3E3;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        box-shadow: 0px 1.5px 4px rgba(26, 26, 25, 0.08);
    }}
    [data-testid="stMetricLabel"] {{ color: #414141; }}
    [data-testid="stMetricValue"] {{ color: {BRAND_COLOR_DARK}; }}
</style>
""", unsafe_allow_html=True)

conn = st.connection("snowflake")

# =============================================================================
# Navigation
# =============================================================================
PAGES = [
    "Dashboard",
    "Action Queue",
    "Encounter Review",
    "ICD-10 Reference",
    "Pipeline",
    "Costs",
    "Upload",
]

with st.sidebar:
    st.markdown(f"""
    <div style="text-align: center; padding: 0.5rem 0;">
        <h2 style="color: {BRAND_COLOR}; margin: 0; font-size: 1.3rem;">{BRAND_NAME}</h2>
        <p style="color: {BRAND_COLOR_DARK}; font-size: 0.7rem; margin: 0;">{BRAND_SUBTITLE}</p>
    </div>
    """, unsafe_allow_html=True)
    st.divider()
    page = st.radio("", PAGES, label_visibility="collapsed")
    st.divider()
    try:
        quick = conn.query(f"""
            SELECT
                (SELECT COUNT(DISTINCT ENCOUNTER_ID) FROM {raw('ENCOUNTER_DIAGNOSES')}) AS PROCESSED,
                (SELECT COUNT(*) FROM {raw('ENCOUNTER_ICD_CODES_ASSIGNED')} WHERE RA_2026_V28 = TRUE) AS RA_CODES,
                (SELECT COUNT(*) FROM {raw('ENCOUNTERS')}) AS TOTAL_ENC
        """, ttl=30)
        if not quick.empty:
            st.metric("Encounters processed", int(quick.iloc[0]["PROCESSED"]))
            st.metric("RA codes found", int(quick.iloc[0]["RA_CODES"]))
    except Exception:
        pass
    st.divider()
    st.caption("Powered by Snowflake Cortex AI")
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/f/ff/Snowflake_Logo.svg/120px-Snowflake_Logo.svg.png", width=80)

# =============================================================================
# Shared data loaders
# =============================================================================
@st.cache_data(ttl=30)
def load_coding_results():
    return conn.query(f"""
        SELECT v.MEMBER_ID, v.MEMBER_FIRST, v.MEMBER_LAST, v.MEMBER_DOB,
               v.SERVICE_START_DATE, v.ENCOUNTER_ID, v.DIAGNOSIS_ID,
               v.DIAGNOSIS_TEXT, v.DX_EVIDENCE, v.DX_CONFIDENCE,
               v.ASSIGNED_ICD_CODE, v.ASSIGNED_DESCRIPTION,
               v.HCC_V28, v.RA_2026_V28, v.RATIONALE,
               v.CODING_CONFIDENCE, v.MISSED_REVENUE
        FROM {harmonized('VW_ENCOUNTER_ICD_CODING')} v
        ORDER BY v.MISSED_REVENUE DESC, v.CODING_CONFIDENCE DESC
    """)

@st.cache_data(ttl=30)
def load_encounters():
    return conn.query(f"""
        SELECT e.ENCOUNTER_ID, e.SOURCE_FILE, e.ENCOUNTER_SEQ, e.MEMBER_ID,
               e.MEMBER_FIRST, e.MEMBER_LAST, e.MEMBER_DOB, e.MEMBER_GENDER,
               e.SERVICE_START_DATE, e.OID, e.MEMBER_CITY, e.MEMBER_STATE,
               e.DIAGNOSIS_CODES, e.NARRATIVES, e.RAW_RECORD,
               q.QUALITY_SCORE, q.QUALITY_CLASSIFICATION
        FROM {raw('ENCOUNTERS')} e
        JOIN {harmonized('ENCOUNTER_QUALITY')} q ON e.ENCOUNTER_ID = q.ENCOUNTER_ID
        ORDER BY e.SERVICE_START_DATE DESC
    """)

# =============================================================================
# PAGE: Dashboard
# =============================================================================
if page == "Dashboard":
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, {BRAND_COLOR} 0%, {BRAND_COLOR_DARK} 100%); padding: 1.25rem 2rem; border-radius: 8px; margin-bottom: 1rem;">
        <h2 style="color: white; margin: 0; font-size: 1.5rem; font-weight: 500;">HEDIS Optimization Dashboard</h2>
        <p style="color: rgba(255,255,255,0.85); margin: 0.25rem 0 0 0; font-size: 0.9rem;">AI-detected ICD-10 codes from clinical narratives not billed on original encounters</p>
    </div>
    """, unsafe_allow_html=True)

    results = load_coding_results()

    if results.empty:
        st.info("No pipeline results yet. Upload encounters and run the pipeline.", icon=":material/info:")
    else:
        missed = results[results["MISSED_REVENUE"] == True]
        ra_codes = results[results["RA_2026_V28"] == True]
        total_codes = len(results)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Missed RA Codes", len(missed), help="Risk-adjusted codes found in narrative but NOT on original claim")
        c2.metric("Total RA Codes Found", len(ra_codes))
        c3.metric("Unique Members Affected", missed["MEMBER_ID"].nunique() if not missed.empty else 0)
        c4.metric("Total Diagnoses Coded", total_codes)

        st.divider()

        st.subheader("Missed risk-adjusted codes")
        if not missed.empty:
            display_missed = missed[["MEMBER_ID", "MEMBER_FIRST", "MEMBER_LAST",
                                     "ASSIGNED_ICD_CODE", "ASSIGNED_DESCRIPTION",
                                     "HCC_V28", "DIAGNOSIS_TEXT", "CODING_CONFIDENCE"]].copy()
            display_missed.columns = ["Member ID", "First", "Last", "ICD Code", "Description",
                                      "HCC Category", "Source Diagnosis", "Confidence"]
            st.dataframe(display_missed, use_container_width=True, hide_index=True,
                column_config={"Confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=1, format="%.0%%")})
        else:
            st.success("No missed codes detected.", icon=":material/verified:")

        st.divider()

        st.subheader("HEDIS measure eligibility")
        hedis_icd = conn.query(f"""
            SELECT
                CASE
                    WHEN HCC_V28 IN ('19','20','21','22','23','36','37','38') THEN 'CDC - Diabetes Care'
                    WHEN HCC_V28 IN ('221','222','223','224','225','226') THEN 'CBP - Blood Pressure'
                    WHEN HCC_V28 IN ('155','156','157','158','159') THEN 'DSF - Depression'
                    WHEN HCC_V28 IN ('1','2','3','4','5','6','7','8','9','10','11','12') THEN 'Cancer Screening'
                    ELSE 'Other HCC (' || HCC_V28 || ')'
                END AS HEDIS_CATEGORY,
                COUNT(*) AS CODE_COUNT,
                COUNT(DISTINCT MEMBER_ID) AS MEMBERS
            FROM {harmonized('VW_ENCOUNTER_ICD_CODING')}
            WHERE RA_2026_V28 = TRUE AND HCC_V28 IS NOT NULL
            GROUP BY HEDIS_CATEGORY
            ORDER BY CODE_COUNT DESC
        """, ttl=30)

        if not hedis_icd.empty:
            st.dataframe(hedis_icd, use_container_width=True, hide_index=True)
        else:
            st.info("No HEDIS-eligible codes detected yet.", icon=":material/info:")

# =============================================================================
# PAGE: Action Queue
# =============================================================================
if page == "Action Queue":
    st.header("HEDIS Gap Closure — Action Queue")
    st.caption("Prioritized interventions based on AI-detected diagnoses and member demographics.")

    results = load_coding_results()
    encounters = load_encounters()

    if results.empty:
        st.info("No results yet.", icon=":material/info:")
    else:
        missed = results[results["MISSED_REVENUE"] == True]

        st.subheader("Priority actions")
        st.markdown("These members have **risk-adjusted ICD codes detected in their clinical narratives** that were not submitted on the original encounter.")

        if not missed.empty:
            member_actions = missed.groupby(["MEMBER_ID", "MEMBER_FIRST", "MEMBER_LAST"]).agg(
                Missed_Codes=("ASSIGNED_ICD_CODE", "count"),
                HCC_Categories=("HCC_V28", lambda x: ", ".join(sorted(set(x.dropna().astype(str))))),
                Codes=("ASSIGNED_ICD_CODE", lambda x: ", ".join(sorted(set(x.dropna())))),
                Avg_Confidence=("CODING_CONFIDENCE", "mean"),
            ).reset_index().sort_values("Missed_Codes", ascending=False)
            member_actions.columns = ["Member ID", "First", "Last", "Missed Codes", "HCC Categories", "ICD Codes", "Avg Confidence"]

            st.dataframe(member_actions, use_container_width=True, hide_index=True,
                column_config={"Avg Confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=1, format="%.0%%")})

            st.divider()

            st.subheader("Review & decide")
            st.caption("Accept or reject each AI-suggested code. Decisions are saved for audit.")

            reviewer = st.text_input("Reviewer name", key="aq_reviewer", placeholder="Enter your name")

            for _, member in member_actions.head(10).iterrows():
                member_missed = missed[missed["MEMBER_ID"] == member["Member ID"]]
                with st.expander(f"**{member['First'] or '?'} {member['Last'] or '?'}** — {member['Missed Codes']} missed code(s)"):
                    for idx, (_, code) in enumerate(member_missed.iterrows()):
                        col_info, col_action = st.columns([3, 1])
                        with col_info:
                            st.markdown(f"**`{code['ASSIGNED_ICD_CODE']}`** — {code['ASSIGNED_DESCRIPTION']}")
                            st.markdown(f"""
| | |
|---|---|
| **HCC category** | {code['HCC_V28'] or '—'} |
| **Confidence** | {code['CODING_CONFIDENCE']:.0%} |
| **Diagnosis found** | {code['DIAGNOSIS_TEXT']} |
| **Evidence from note** | _{code['DX_EVIDENCE'] or code.get('RATIONALE', '—')}_ |
| **AI rationale** | {code['RATIONALE']} |
""")
                        with col_action:
                            key_prefix = f"aq_{code['ENCOUNTER_ID']}_{code['ASSIGNED_ICD_CODE']}_{idx}"
                            decision = st.radio("Decision", ["Pending", "Accept", "Reject"],
                                key=f"{key_prefix}_decision", horizontal=True, label_visibility="collapsed")
                            if decision != "Pending" and reviewer:
                                if st.button("Save", key=f"{key_prefix}_save", type="primary"):
                                    try:
                                        with conn._instance.cursor() as cur:
                                            cur.execute(f"""
                                                INSERT INTO {raw('CODE_REVIEW_DECISIONS')}
                                                (ASSIGNMENT_ID, ENCOUNTER_ID, ICD_CODE, DECISION, REVIEWER_NAME)
                                                VALUES ('{code.get('DIAGNOSIS_ID', '')}', '{code['ENCOUNTER_ID']}',
                                                        '{code['ASSIGNED_ICD_CODE']}', '{decision.upper()}', '{reviewer}')
                                            """)
                                        st.success(f"{decision}ed", icon=":material/check:")
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                        st.markdown("---")
        else:
            st.success("No open action items.", icon=":material/verified:")

# =============================================================================
# PAGE: Encounter Review
# =============================================================================
if page == "Encounter Review":
    encounters = load_encounters()

    if encounters.empty:
        st.info("No encounters loaded.", icon=":material/info:")
    else:
        patients = encounters.drop_duplicates(subset=["MEMBER_ID"]).copy()
        patients["LABEL"] = patients.apply(
            lambda r: f"{r['MEMBER_FIRST'] or ''} {r['MEMBER_LAST'] or ''} — {r['MEMBER_ID']}".strip(), axis=1)
        patients = patients[
            patients.apply(lambda r: bool(r['MEMBER_FIRST'] and r['MEMBER_LAST']
                                          and str(r['MEMBER_FIRST']).strip() and str(r['MEMBER_LAST']).strip()), axis=1)]
        if patients.empty:
            patients = encounters.drop_duplicates(subset=["MEMBER_ID"]).copy()
            patients["LABEL"] = patients["MEMBER_ID"]

        pick1, pick2 = st.columns([1, 1])
        with pick1:
            selected_member = st.selectbox("Patient", patients["MEMBER_ID"].tolist(),
                format_func=lambda mid: patients[patients["MEMBER_ID"] == mid].iloc[0]["LABEL"], key="rv3_patient")
        with pick2:
            member_encs = encounters[encounters["MEMBER_ID"] == selected_member].sort_values("SERVICE_START_DATE", ascending=False)
            selected_id = st.selectbox(f"Encounter ({len(member_encs)})", member_encs["ENCOUNTER_ID"].tolist(),
                format_func=lambda eid: f"Seq {member_encs[member_encs['ENCOUNTER_ID']==eid].iloc[0]['ENCOUNTER_SEQ']} — {member_encs[member_encs['ENCOUNTER_ID']==eid].iloc[0]['SERVICE_START_DATE']}",
                key="rv3_encounter")

        enc = member_encs[member_encs["ENCOUNTER_ID"] == selected_id].iloc[0]

        # Section 1: Encounter facts
        st.divider()
        st.subheader("Encounter summary")
        dem_col1, dem_col2, dem_col3, dem_col4, dem_col5, dem_col6 = st.columns(6)
        dem_col1.markdown(f"**Member ID**  \n`{enc['MEMBER_ID']}`")
        dem_col2.markdown(f"**Name**  \n{enc['MEMBER_FIRST'] or '—'} {enc['MEMBER_LAST'] or '—'}")
        dem_col3.markdown(f"**DOB**  \n{enc['MEMBER_DOB'] or '—'}")
        dem_col4.markdown(f"**Gender**  \n{enc['MEMBER_GENDER'] or '—'}")
        dem_col5.markdown(f"**Location**  \n{enc['MEMBER_CITY'] or '—'}, {enc['MEMBER_STATE'] or '—'}")
        dem_col6.markdown(f"**Quality**  \n`{enc['QUALITY_CLASSIFICATION']}`")

        svc_col1, svc_col2, svc_col3, svc_col4 = st.columns(4)
        svc_col1.markdown(f"**Service date**  \n{enc['SERVICE_START_DATE']}")
        svc_col2.markdown(f"**Facility**  \n{enc['OID'] or '—'}")
        svc_col3.markdown(f"**Source file**  \n`{enc['SOURCE_FILE'].split('/')[-1] if enc['SOURCE_FILE'] else '—'}`")
        svc_col4.markdown(f"**Encounter seq**  \n{enc['ENCOUNTER_SEQ']}")

        st.markdown("**Original diagnosis codes on encounter:**")
        diag = enc.get("DIAGNOSIS_CODES")
        if diag:
            if isinstance(diag, str):
                diag = json.loads(diag)
            if isinstance(diag, list) and diag:
                diag_rows = []
                for item in diag:
                    if isinstance(item, str):
                        item = json.loads(item)
                    diag_rows.append({"Code": item.get("Code", ""), "System": item.get("Qualifier", "")})
                st.dataframe(pd.DataFrame(diag_rows), use_container_width=True, hide_index=True, height=120)
        else:
            st.caption("None")

        with st.expander("Raw encounter JSON", icon=":material/data_object:"):
            raw_rec = enc.get("RAW_RECORD")
            if raw_rec:
                if isinstance(raw_rec, str):
                    try:
                        st.json(json.loads(raw_rec))
                    except:
                        st.code(raw_rec, language="json")
                else:
                    st.json(raw_rec)

        # Section 2: AI-assigned ICD codes
        st.divider()
        st.subheader("AI-assigned ICD-10 codes")
        st.caption("Each code is grounded — selected from real CMS ICD-10 reference codes only.")

        assigned = conn.query(f"""
            SELECT a.ASSIGNED_ICD_CODE, a.ASSIGNED_DESCRIPTION, a.HCC_V28,
                   a.RA_2026_V28, a.CONFIDENCE, a.RATIONALE,
                   d.DIAGNOSIS_TEXT, d.EVIDENCE, d.SOURCE_NARRATIVE_TYPE
            FROM {raw('ENCOUNTER_ICD_CODES_ASSIGNED')} a
            JOIN {raw('ENCOUNTER_DIAGNOSES')} d ON a.DIAGNOSIS_ID = d.DIAGNOSIS_ID
            WHERE a.ENCOUNTER_ID = '{selected_id}'
            ORDER BY a.RA_2026_V28 DESC, a.CONFIDENCE DESC
        """, ttl=15)

        ai_codes_view = conn.query(f"""
            SELECT ASSIGNED_ICD_CODE, MISSED_REVENUE
            FROM {harmonized('VW_ENCOUNTER_ICD_CODING')}
            WHERE ENCOUNTER_ID = '{selected_id}'
        """, ttl=15)
        missed_set = set()
        if not ai_codes_view.empty:
            missed_set = set(ai_codes_view[ai_codes_view["MISSED_REVENUE"] == True]["ASSIGNED_ICD_CODE"].tolist())

        if not assigned.empty:
            reviewer_enc = st.text_input("Reviewer", key="enc_reviewer", placeholder="Your name")

            for idx, code in assigned.iterrows():
                is_missed = code["ASSIGNED_ICD_CODE"] in missed_set
                missed_label = "**NEW — Not on original claim**" if is_missed else "Already billed"
                ra_tag = ":green-badge[Risk Adjusted]" if code["RA_2026_V28"] else ":gray-badge[Non-RA]"
                hcc_tag = f":blue-badge[HCC {code['HCC_V28']}]" if code["HCC_V28"] else ""

                header_col, action_col = st.columns([3, 1])
                with header_col:
                    st.markdown(f"#### `{code['ASSIGNED_ICD_CODE']}` — {code['ASSIGNED_DESCRIPTION']}")
                    st.markdown(f"{ra_tag} {hcc_tag} · Confidence: **{code['CONFIDENCE']:.0%}** · {missed_label}")
                with action_col:
                    key_pfx = f"er_{selected_id}_{code['ASSIGNED_ICD_CODE']}_{idx}"
                    decision = st.radio("", ["Pending", "Accept", "Reject"],
                                        key=f"{key_pfx}_d", horizontal=True, label_visibility="collapsed")
                    if decision != "Pending" and reviewer_enc:
                        if st.button("Save", key=f"{key_pfx}_s", type="primary"):
                            try:
                                with conn._instance.cursor() as cur:
                                    cur.execute(f"""
                                        INSERT INTO {raw('CODE_REVIEW_DECISIONS')}
                                        (ENCOUNTER_ID, ICD_CODE, DECISION, REVIEWER_NAME)
                                        VALUES ('{selected_id}', '{code['ASSIGNED_ICD_CODE']}',
                                                '{decision.upper()}', '{reviewer_enc}')
                                    """)
                                st.success(f"{decision}ed")
                            except Exception as e:
                                st.error(str(e))

                st.markdown(f"""
| Citation | Detail |
|----------|--------|
| **Diagnosis found** | {code['DIAGNOSIS_TEXT']} |
| **Quoted evidence** | _{code['EVIDENCE']}_ |
| **Note type** | {code['SOURCE_NARRATIVE_TYPE']} |
| **AI rationale** | {code['RATIONALE']} |
""")
                st.markdown("---")
        else:
            st.info("No codes assigned yet. Run the pipeline to process this encounter.", icon=":material/info:")

        # Section 3: Clinical narratives
        st.divider()
        st.subheader("Clinical narratives")
        st.caption("Evidence phrases are highlighted in orange where they match AI-extracted diagnoses.")

        narratives = enc.get("NARRATIVES")
        evidence_phrases = conn.query(f"""
            SELECT DISTINCT EVIDENCE FROM {raw('ENCOUNTER_DIAGNOSES')}
            WHERE ENCOUNTER_ID = '{selected_id}' AND EVIDENCE IS NOT NULL
        """, ttl=30)
        highlight_phrases = set()
        if not evidence_phrases.empty:
            highlight_phrases = set(evidence_phrases["EVIDENCE"].tolist())

        if narratives:
            if isinstance(narratives, str):
                narratives = json.loads(narratives)
            if isinstance(narratives, list):
                for narr in narratives:
                    if isinstance(narr, str):
                        narr = json.loads(narr)
                    narr_type = narr.get("Type", "Note")
                    narr_value = narr.get("Value", "")
                    clean_text = re.sub(r'<[^>]+>', ' ', narr_value).strip()
                    clean_text = re.sub(r'\s+', ' ', clean_text)
                    display_text = clean_text
                    for phrase in highlight_phrases:
                        if phrase and phrase in display_text:
                            display_text = display_text.replace(phrase, f"**:orange[{phrase}]**")
                    with st.expander(f"{narr_type}", expanded=True):
                        st.markdown(display_text[:4000])

        # Section 4: Candidates & timeline
        st.divider()
        col_cand, col_timeline = st.columns(2)

        with col_cand:
            st.markdown("**Candidate codes considered**")
            candidates = conn.query(f"""
                SELECT c.ICD_CODE AS Code, c.ICD_DESCRIPTION AS Description,
                       c.SEARCH_RANK AS Rank, c.RA_2026_V28 AS RA,
                       d.DIAGNOSIS_TEXT AS "Source Diagnosis",
                       CASE WHEN a.ASSIGNED_ICD_CODE = c.ICD_CODE THEN TRUE ELSE FALSE END AS Chosen
                FROM {raw('ENCOUNTER_DX_CANDIDATES')} c
                JOIN {raw('ENCOUNTER_DIAGNOSES')} d ON c.DIAGNOSIS_ID = d.DIAGNOSIS_ID
                LEFT JOIN {raw('ENCOUNTER_ICD_CODES_ASSIGNED')} a ON c.DIAGNOSIS_ID = a.DIAGNOSIS_ID
                WHERE c.ENCOUNTER_ID = '{selected_id}'
                ORDER BY d.DIAGNOSIS_TEXT, c.SEARCH_RANK
            """, ttl=15)
            if not candidates.empty:
                with st.expander(f"{len(candidates)} candidates evaluated"):
                    st.dataframe(candidates, use_container_width=True, hide_index=True,
                        column_config={"Chosen": st.column_config.CheckboxColumn(), "RA": st.column_config.CheckboxColumn()})

        with col_timeline:
            st.markdown("**Processing timeline**")
            timeline = conn.query(f"""
                SELECT 'Extract diagnoses' AS Step, COUNT(*) AS Items, MIN(EXTRACTED_AT) AS Completed
                FROM {raw('ENCOUNTER_DIAGNOSES')} WHERE ENCOUNTER_ID = '{selected_id}'
                UNION ALL
                SELECT 'Retrieve candidates', COUNT(*), MIN(RETRIEVED_AT)
                FROM {raw('ENCOUNTER_DX_CANDIDATES')} WHERE ENCOUNTER_ID = '{selected_id}'
                UNION ALL
                SELECT 'Assign codes', COUNT(*), MIN(ASSIGNED_AT)
                FROM {raw('ENCOUNTER_ICD_CODES_ASSIGNED')} WHERE ENCOUNTER_ID = '{selected_id}'
                ORDER BY Completed
            """, ttl=15)
            if not timeline.empty:
                st.dataframe(timeline, use_container_width=True, hide_index=True)

# =============================================================================
# PAGE: ICD-10 Reference
# =============================================================================
if page == "ICD-10 Reference":
    st.header("ICD-10 / HCC Reference")
    st.caption("Browse all indexed ICD-10-CM codes with HCC category mappings and risk adjustment status.")

    search_col1, search_col2 = st.columns([3, 1])
    with search_col1:
        search_term = st.text_input("Search by code or description", key="ref_search", placeholder="e.g., E11, diabetes, hypertension, J44")
    with search_col2:
        ra_filter = st.selectbox("RA status (V28)", ["All", "Risk Adjusted", "Not Risk Adjusted"], key="ref_ra_filter")

    where_clauses = ["1=1"]
    if search_term:
        safe_term = search_term.replace("'", "''")
        where_clauses.append(f"(ICD_CODE ILIKE '%{safe_term}%' OR DESCRIPTION ILIKE '%{safe_term}%')")
    if ra_filter == "Risk Adjusted":
        where_clauses.append("RA_2026_V28 = TRUE")
    elif ra_filter == "Not Risk Adjusted":
        where_clauses.append("RA_2026_V28 = FALSE")

    ref_data = conn.query(f"""
        SELECT ICD_CODE, DESCRIPTION, HCC_V28, HCC_ESRD_V24, RA_2026_V28, RA_2026_ESRD_V24
        FROM {raw('ICD10_HCC_MAPPINGS')}
        WHERE {' AND '.join(where_clauses)}
        ORDER BY ICD_CODE
        LIMIT 500
    """, ttl=60)

    total_in_ref = conn.query(f"SELECT COUNT(*) AS CNT, COUNT(CASE WHEN RA_2026_V28 THEN 1 END) AS RA FROM {raw('ICD10_HCC_MAPPINGS')}", ttl=120)
    if not total_in_ref.empty:
        m1, m2, m3 = st.columns(3)
        m1.metric("Total indexed codes", f"{int(total_in_ref.iloc[0]['CNT']):,}")
        m2.metric("Risk-adjustable (V28)", f"{int(total_in_ref.iloc[0]['RA']):,}")
        m3.metric("Showing", f"{len(ref_data)} results")

    if not ref_data.empty:
        st.dataframe(ref_data, use_container_width=True, hide_index=True, height=500,
            column_config={
                "ICD_CODE": st.column_config.TextColumn("ICD-10 Code"),
                "DESCRIPTION": st.column_config.TextColumn("Description"),
                "HCC_V28": st.column_config.TextColumn("HCC (V28)"),
                "HCC_ESRD_V24": st.column_config.TextColumn("HCC (V24)"),
                "RA_2026_V28": st.column_config.CheckboxColumn("RA (V28)"),
                "RA_2026_ESRD_V24": st.column_config.CheckboxColumn("RA (V24)"),
            })
    else:
        st.info("No codes match your search.", icon=":material/search_off:")

    st.divider()
    st.subheader("Browse by HCC category")
    hcc_cats = conn.query(f"""
        SELECT HCC_V28, COUNT(*) AS CODE_COUNT
        FROM {raw('ICD10_HCC_MAPPINGS')}
        WHERE HCC_V28 IS NOT NULL AND HCC_V28 != ''
        GROUP BY HCC_V28
        ORDER BY CODE_COUNT DESC
    """, ttl=120)

    if not hcc_cats.empty:
        selected_hcc = st.selectbox("Select HCC category", hcc_cats["HCC_V28"].tolist(),
            format_func=lambda h: f"HCC {h} ({hcc_cats[hcc_cats['HCC_V28']==h].iloc[0]['CODE_COUNT']} codes)",
            key="ref_hcc_select")
        if selected_hcc:
            hcc_codes = conn.query(f"""
                SELECT ICD_CODE, DESCRIPTION, RA_2026_V28
                FROM {raw('ICD10_HCC_MAPPINGS')}
                WHERE HCC_V28 = '{selected_hcc}'
                ORDER BY ICD_CODE
            """, ttl=60)
            st.dataframe(hcc_codes, use_container_width=True, hide_index=True,
                column_config={"RA_2026_V28": st.column_config.CheckboxColumn("RA (V28)")})

# =============================================================================
# PAGE: Pipeline
# =============================================================================
if page == "Pipeline":
    st.header("ICD-10 coding pipeline")
    st.caption("Retrieval-grounded architecture — every assigned code is a real CMS billable code, never hallucinated.")

    diag_count = conn.query(f"SELECT COUNT(*) AS CNT FROM {raw('ENCOUNTER_DIAGNOSES')}", ttl=10)
    cand_count = conn.query(f"SELECT COUNT(*) AS CNT FROM {raw('ENCOUNTER_DX_CANDIDATES')}", ttl=10)
    assign_count = conn.query(f"SELECT COUNT(*) AS CNT FROM {raw('ENCOUNTER_ICD_CODES_ASSIGNED')}", ttl=10)
    enc_total = conn.query(f"SELECT COUNT(*) AS CNT FROM {raw('ENCOUNTERS')}", ttl=10)

    st.subheader("Current pipeline state")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Encounters", int(enc_total.iloc[0]["CNT"]))
    c2.metric("Diagnoses extracted", int(diag_count.iloc[0]["CNT"]))
    c3.metric("Candidates retrieved", int(cand_count.iloc[0]["CNT"]))
    c4.metric("Codes assigned", int(assign_count.iloc[0]["CNT"]))

    st.divider()
    st.subheader("Design principles")
    st.markdown("""
| Principle | How it's implemented |
|-----------|---------------------|
| **No hallucinated codes** | Step 3 is constrained to pick ONLY from codes returned by Cortex Search in Step 2 |
| **Every code is real** | The search index contains only official CMS ICD-10-CM codes from the FY2026 reference |
| **Evidence-linked** | Each assigned code traces back to a specific quote from the clinical narrative |
| **Idempotent** | Each step checks for already-processed records before running (safe to re-run) |
| **Cost-tracked** | All AI calls are tagged for precise attribution |
| **Auto-triggered** | Snowflake Stream + Task DAG runs within 1 minute of new data arriving |
""")

    st.divider()

    def run_procedure(proc_call):
        with conn._instance.cursor() as cur:
            cur.execute(proc_call)
            return cur.fetchone()

    with st.expander("Manual pipeline trigger", icon=":material/play_arrow:"):
        st.caption("Use if the automatic task is suspended or for testing.")
        if st.button("Run full pipeline", key="manual_run"):
            with st.spinner("Step 1: Extracting diagnoses..."):
                run_procedure(f"CALL {raw('SP_EXTRACT_DIAGNOSES')}(NULL)")
            with st.spinner("Step 2: Retrieving candidates..."):
                run_procedure(f"CALL {raw('SP_RETRIEVE_CANDIDATES')}(NULL)")
            with st.spinner("Step 3: Assigning codes..."):
                run_procedure(f"CALL {raw('SP_ASSIGN_ICD_CODES')}(NULL)")
            st.success("Complete!", icon=":material/check_circle:")
            st.rerun()

# =============================================================================
# PAGE: Costs
# =============================================================================
if page == "Costs":
    st.header("Pipeline costs")
    st.caption("Actual costs from the latest pipeline run, plus a calculator for projecting costs at scale.")

    st.subheader("Latest run")
    enc_total = conn.query(f"SELECT COUNT(*) AS CNT FROM {raw('ENCOUNTERS')}", ttl=10)
    try:
        run_ids = conn.query("""
            SELECT DISTINCT REGEXP_SUBSTR(QUERY_TAG, ':[0-9]{8}_[0-9]{6}$') AS RUN_SUFFIX
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
            WHERE QUERY_TAG LIKE 'chart_review::%'
            AND QUERY_TAG RLIKE '.*:[0-9]{8}_[0-9]{6}$'
            AND START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
            ORDER BY RUN_SUFFIX DESC
            LIMIT 1
        """, ttl=120)

        if not run_ids.empty and run_ids.iloc[0]["RUN_SUFFIX"]:
            run_id = run_ids.iloc[0]["RUN_SUFFIX"][1:]
            st.caption(f"Run: `{run_id}`")

            pipeline_costs = conn.query(f"""
                SELECT
                    REGEXP_REPLACE(QUERY_TAG, ':[0-9]{{8}}_[0-9]{{6}}$', '') AS STEP,
                    FUNCTION_NAME, MODEL_NAME,
                    COUNT(*) AS CALLS, SUM(CREDITS) AS CREDITS
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
                WHERE QUERY_TAG LIKE '%{run_id}'
                AND START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                GROUP BY STEP, FUNCTION_NAME, MODEL_NAME
                ORDER BY CREDITS DESC
            """, ttl=120)

            if not pipeline_costs.empty:
                total_credits = float(pipeline_costs["CREDITS"].sum())
                total_calls = int(pipeline_costs["CALLS"].sum())
                enc_val = int(enc_total.iloc[0]["CNT"])

                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Total credits (this run)", f"{total_credits:.6f}")
                mc2.metric("AI calls", total_calls)
                mc3.metric("Cost/encounter", f"{total_credits/enc_val:.6f}" if enc_val > 0 else "—")
                st.dataframe(pipeline_costs, use_container_width=True, hide_index=True)
            else:
                st.caption("No cost data for this run yet (ACCOUNT_USAGE has ~2hr latency).")
        else:
            st.caption("No timestamped pipeline runs found in the last 7 days.")
    except Exception as e:
        st.caption(f"Cost data unavailable: {e}")

    st.divider()

    st.subheader("Cost calculator")
    st.caption("Adjust parameters to project pipeline costs at different scales.")

    calc_col1, calc_col2, calc_col3 = st.columns(3)

    with calc_col1:
        st.markdown("**Volume inputs**")
        num_encounters = st.number_input("Encounters per month", min_value=1, value=10000, step=1000, key="calc_enc")
        avg_diagnoses = st.number_input("Avg diagnoses per encounter", min_value=1, value=17, step=1, key="calc_diag")
        num_candidates = st.number_input("ICD-10 codes retrieved per diagnosis", min_value=1, value=10, step=1, key="calc_candidates")

    with calc_col2:
        st.markdown("**Token sizes**")
        avg_narrative_tokens = st.number_input("Avg narrative tokens", min_value=100, value=1500, step=100, key="calc_narr")
        step1_prompt_tokens = st.number_input("Step 1 prompt tokens", min_value=50, value=200, step=10, key="calc_s1_prompt")
        step1_output_per_diag = st.number_input("Step 1 output tokens/diagnosis", min_value=10, value=85, step=5, key="calc_s1_out")
        step3_prompt_tokens = st.number_input("Step 3 prompt tokens", min_value=50, value=120, step=10, key="calc_s3_prompt")
        step3_tokens_per_candidate = st.number_input("Tokens per candidate", min_value=10, value=50, step=5, key="calc_s3_cand")
        step3_output_tokens_per = st.number_input("Step 3 output tokens", min_value=20, value=275, step=10, key="calc_s3_out")

    with calc_col3:
        st.markdown("**Credit rates (per 1M tokens)**")
        rate_claude_input = st.number_input("claude-sonnet input", min_value=0.0, value=1.80, step=0.01, key="calc_rate_in", format="%.2f")
        rate_claude_output = st.number_input("claude-sonnet output", min_value=0.0, value=9.00, step=0.01, key="calc_rate_out", format="%.2f")
        rate_embed = st.number_input("arctic-embed embedding", min_value=0.0, value=0.030, step=0.001, key="calc_rate_embed", format="%.3f")
        st.markdown("**Credit pricing ($/credit)**")
        credit_price = st.radio("Credit type", ["Global ($1.92)", "Region-specific ($2.11)"], key="calc_credit_type", horizontal=True)
        price_per_credit = 1.92 if "Global" in credit_price else 2.11

    st.divider()

    step1_input_tokens = (step1_prompt_tokens + avg_narrative_tokens) * num_encounters
    step1_output_tokens = (step1_output_per_diag * avg_diagnoses) * num_encounters
    step1_credits = (step1_input_tokens * rate_claude_input / 1_000_000) + (step1_output_tokens * rate_claude_output / 1_000_000)
    total_diagnoses = num_encounters * avg_diagnoses
    step2_tokens = 20 * total_diagnoses
    step2_credits = step2_tokens * rate_embed / 1_000_000
    step3_input_per_call = step3_prompt_tokens + 50 + (num_candidates * step3_tokens_per_candidate)
    step3_input_tokens = step3_input_per_call * total_diagnoses
    step3_output_tokens = step3_output_tokens_per * total_diagnoses
    step3_credits = (step3_input_tokens * rate_claude_input / 1_000_000) + (step3_output_tokens * rate_claude_output / 1_000_000)
    total_credits_calc = step1_credits + step2_credits + step3_credits
    cost_per_encounter_calc = total_credits_calc / num_encounters if num_encounters > 0 else 0
    total_cost_dollars = total_credits_calc * price_per_credit
    cost_per_enc_dollars = cost_per_encounter_calc * price_per_credit

    st.markdown("**Projected costs**")
    res_col1, res_col2, res_col3, res_col4, res_col5 = st.columns(5)
    res_col1.metric("Credits/month", f"{total_credits_calc:,.2f}")
    res_col2.metric("$/month", f"${total_cost_dollars:,.2f}")
    res_col3.metric("Credits/encounter", f"{cost_per_encounter_calc:.6f}")
    res_col4.metric("$/encounter", f"${cost_per_enc_dollars:.4f}")
    res_col5.metric("Total encounters", f"{num_encounters:,}")

    st.markdown("**Breakdown by step**")
    breakdown = pd.DataFrame([
        {"Step": "1. Extract diagnoses", "Calls": num_encounters, "Input tokens": f"{step1_input_tokens:,}", "Output tokens": f"{step1_output_tokens:,}", "Credits": f"{step1_credits:.4f}", "Cost ($)": f"${step1_credits * price_per_credit:.2f}"},
        {"Step": "2. Retrieve candidates", "Calls": total_diagnoses, "Input tokens": f"{step2_tokens:,}", "Output tokens": "—", "Credits": f"{step2_credits:.4f}", "Cost ($)": f"${step2_credits * price_per_credit:.2f}"},
        {"Step": "3. Assign codes", "Calls": total_diagnoses, "Input tokens": f"{step3_input_tokens:,}", "Output tokens": f"{step3_output_tokens:,}", "Credits": f"{step3_credits:.4f}", "Cost ($)": f"${step3_credits * price_per_credit:.2f}"},
        {"Step": "**Total**", "Calls": num_encounters + 2*total_diagnoses, "Input tokens": f"{step1_input_tokens + step2_tokens + step3_input_tokens:,}", "Output tokens": f"{step1_output_tokens + step3_output_tokens:,}", "Credits": f"{total_credits_calc:.4f}", "Cost ($)": f"${total_cost_dollars:.2f}"},
    ])
    st.dataframe(breakdown, use_container_width=True, hide_index=True)
    st.caption(f"At {num_encounters:,} encounters/month with {avg_diagnoses} diagnoses each: **{total_credits_calc:,.2f} credits/month = ${total_cost_dollars:,.2f}/month** @ ${price_per_credit:.2f}/credit")

# =============================================================================
# PAGE: Upload
# =============================================================================
if page == "Upload":
    st.header("Upload encounters")
    st.caption("Upload JSONL encounter files. New encounters are automatically processed by the pipeline within ~1 minute.")

    uploaded_jsonl = st.file_uploader("Select JSONL files", type=["jsonl", "json"], accept_multiple_files=True, key="v3_uploader")

    if uploaded_jsonl:
        if st.button("Load encounters", type="primary", icon=":material/cloud_upload:"):
            total_loaded = 0
            progress = st.progress(0)
            for i, file in enumerate(uploaded_jsonl):
                temp_path = f"/tmp/{file.name}"
                with open(temp_path, "wb") as f:
                    f.write(file.getbuffer())
                conn.query(f"""
                    PUT 'file://{temp_path}' @{raw('ENCOUNTER_STAGE')}/encounters/
                    AUTO_COMPRESS=TRUE OVERWRITE=TRUE
                """)
                result = conn.query(f"""
                    COPY INTO {raw('ENCOUNTERS')} (
                        SOURCE_FILE, ENCOUNTER_SEQ, SERVICE_START_DATE, SERVICE_END_DATE,
                        CCD_STATUS, MEMBER_ID, MEMBER_FIRST, MEMBER_LAST, MEMBER_DOB,
                        MEMBER_GENDER, MEMBER_ADDRESS, MEMBER_CITY, MEMBER_STATE, MEMBER_ZIP,
                        OID, PROVIDER_TIN, SOURCE_SYSTEM, CDR_LOAD_DATE,
                        DIAGNOSIS_CODES, NARRATIVES, PERFORMERS, RAW_RECORD
                    )
                    FROM (
                        SELECT
                            METADATA$FILENAME,
                            $1:Encounter_SeqNumber::VARCHAR,
                            TRY_TO_TIMESTAMP($1:ServiceStartDate::VARCHAR),
                            TRY_TO_TIMESTAMP($1:ServiceEndDate::VARCHAR),
                            $1:CCDStatus::VARCHAR,
                            $1:MemberID::VARCHAR,
                            $1:MemberFirst::VARCHAR,
                            $1:MemberLast::VARCHAR,
                            TRY_TO_DATE($1:MemberDOB::VARCHAR),
                            $1:MemberGender::VARCHAR,
                            $1:MemberAddress::VARCHAR,
                            $1:MemberCity::VARCHAR,
                            $1:MemberState::VARCHAR,
                            $1:MemberZip::VARCHAR,
                            $1:OID::VARCHAR,
                            $1:ProviderTin::VARCHAR,
                            $1:SourceSystem::VARCHAR,
                            TRY_TO_TIMESTAMP($1:CDRLoadDate::VARCHAR),
                            $1:DiagnosisCodes,
                            $1:Narratives,
                            $1:Performer,
                            $1
                        FROM @{raw('ENCOUNTER_STAGE')}/encounters/{file.name}
                    )
                    FILE_FORMAT = (TYPE = 'JSON' STRIP_OUTER_ARRAY = FALSE)
                    ON_ERROR = 'CONTINUE'
                """)
                if not result.empty:
                    total_loaded += int(result.iloc[0].get("rows_loaded", 0))
                progress.progress((i + 1) / len(uploaded_jsonl))
            st.success(f"Loaded {total_loaded} encounter(s). Pipeline will process automatically.", icon=":material/check_circle:")
