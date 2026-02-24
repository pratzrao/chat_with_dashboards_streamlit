# SHOFCO — Gender Program (Context Pack / Human Notes)

**Program ID:** shofco_gender  
**Owner:** Dalgo / SHOFCO team
**Purpose of this file:** Lightweight “human head” context to ground the Chat-with-Dashboards assistant for SHOFCO’s Gender program.  

---

## 1) What this program is
SHOFCO’s **Gender** program collects and tracks gender-related program data (e.g., GBV, counselling, safe house usage, survivors support, mental health assessments, training sessions, etc.).

This assistant is expected to answer:
- “How many…”, “Trend over time…”, “Breakdown by…”
- “What does this metric mean / how is it calculated?”
- “Which dataset powers this chart?”
- Follow-ups like “same but last month”, “now split by district”, etc.

---

## 2) Source systems (where the data originates)
### 2.1 CommCare
- Primary data collection for Gender program is done in **CommCare**.
- CommCare raw extracts land in the warehouse under the **`staging_gender`** schema.

### 2.2 Google Sheets
- **Gender champions** and **GBV leaders** data comes from **Google Sheets**.
- These raw sheet ingests also land in **`staging_gender`**.

---

## 3) Warehouse / dbt layering (how data is organized)
### 3.1 Schemas by layer
- **Raw / staging:** `staging_gender`  
  Contains raw extracts from CommCare + Google Sheets (minimal transformations).

- **Intermediate:** `prod_intermediate_gender`  
  Cleanups, standardization, deduping, conformed dimensions, derived fields used by marts.

- **Final marts (dashboard-facing):** `prod_gender`  
  This is where final chart-ready models live. Dashboards are built from these.

### 3.2 dbt folder layout (from repo)
- `models/staging/gender/*` → staging models (raw normalization)
- `models/marts/gender/*` → final marts for dashboards

---

## 4) Key dbt models (Gender)
> Note: This list is based on current repo structure. The assistant should still rely on dbt manifest/catalog for authoritative schema + lineage.

### 4.1 Staging (models/staging/gender)
- `staging_champions`
- `staging_gbv_leaders`
- `staging_gender_case_occurrences_commcare`
- `staging_gender_counselling_commcare`
- `staging_gender_final_mental_health_assessment`
- `staging_gender_initial_mental_health_assessment`
- `staging_gender_safe_house_commcare`
- `staging_gender_survivors_commcare`
- `staging_life_skills_training_participant_details`
- `staging_life_skills_training_session_details`
- `staging_youth_beneficiaries`
- `survivors_data`

### 4.2 Final marts (models/marts/gender)
- `case_occurrence`
- `case_occurrence_pii`
- `champions`
- `counselling`
- `gbv_leader`
- `life_skills_training_participants`
- `life_skills_training_sessions`
- `mh_score_improvement_descriptive`
- `safe_house`
- `safe_house_agg`
- `sessions_attended`
- `supported`
- `youth_beneficiaries_disagg`

---
## 5) Definitions
- GBV: Gender Based Violence
- SGBV: Sexual Gender Based Violence - You can get this from GBV by looking at the column cleaned_assault_type in case_occurrence or case_occurrence_pii and filtering that for sexual_violence
- GBV Leaders and Gender Champions: People from the community who are identified and trained and then they help with reporting cases and providing support to survivors
- Conviction rate - depending on the denominator. conviction rate can be for all cases, for cases that went to judgement, to mention etc. the conviction info is in - was_the_perpetrator_convicted in case_occurrence. stage of case in court holds judgement, mentione tc

---

## 6) SQL Query Guidelines (for data analysis questions)

### 6.1 Critical Field Mappings
**For survivor counts**, ALWAYS use: `COUNT_DISTINCT(parent_case_id)`
- "How many survivors" → COUNT_DISTINCT(parent_case_id)
- "Survivors supported" → COUNT_DISTINCT(parent_case_id)  
- "Number of survivors" → COUNT_DISTINCT(parent_case_id)
- This matches the dashboard calculation method

**Geographic analysis**: For breakdowns by location, we have county and constituency in the data. But always check what is in the data, and if qhat the user is asking for is not found, clarify it with them.

**Date filtering**: Use `date_of_case_reporting` column for time-based filters

### 6.2 Main Tables
- `prod_gender.case_occurence` - Main case data (note: spelled "occurence" not "occurrence")  
- `prod_gender.champions` - Gender champion data
- `prod_gender.counselling` - Counselling session data