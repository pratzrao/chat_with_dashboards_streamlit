# BHUMI NGO Programs & Metrics - Human Context Guide

## About BHUMI NGO

**Background & History:**
BHUMI is India's largest independent youth volunteering non-profit organization, founded in 2006 in Chennai on August 15th by Dr. Prahalathan KK, Ayyanar Elumalai, and Dr. Harishankar Namasivayam. What started as a group of young people volunteering to teach children at an orphanage has grown into a nationwide movement.

**Mission & Vision:**
- **Vision:** To help build a more influential, equal, and socially conscious society
- **Mission:** To drive social change by fostering an environment where young adults and children learn, lead and thrive

**Scale & Impact:**
- Over 30,000 active volunteers across 12+ cities in India (as of 2020)
- Educates 25,000+ children annually
- Has engaged 200,000+ volunteers contributing 2.5+ million volunteer hours
- Operating for 18+ years

**Core Focus Areas:**
BHUMI operates two main program verticals:
1. **Ignite (Education):** Direct educational support in government schools and communities
2. **Catalyze (Civic Projects):** Environmental, animal welfare, and community development initiatives


## Programs Overview

### 1. Fellowship Program (Educational Leadership Development)
**What it is:** BHUMI's flagship 2-year paid fellowship program that develops young leaders (ages 20-30) to drive systemic change in education. Fellows work directly in government schools implementing the Whole School Transformation Programme while receiving structured learning, mentorship, and a monthly grant of ₹25,500.

**Program Goals:**
- Transform schools in the short term through direct intervention
- Develop future education leaders for long-term systemic change
- Create a cadre of changemakers with comprehensive understanding of the education ecosystem
- Provide exposure to grassroots organizations, policymakers, and CSR initiatives

**Selection Process:**
- Multi-stage assessment including online application, video submission, and final evaluation
- Final assessment includes lesson execution, group discussion, problem solving, and personal interview
- Emphasis on systems thinking and holistic educational approach

**Data Collection Tools:** Google Sheets-based tracking systems for comprehensive assessment data

**Academic Years Tracked:** 
- AY 2024-25 (fellowship_24_25_data)
- AY 2025-26 (fellowship_25_26)

---

# DBT Data Warehouse Table Guide

## Overview
BHUMI's data warehouse is built using DBT (data build tool) with a structured approach:
- **Raw/Staging Layer**: Raw data ingestion and basic cleaning
- **Intermediate Layer**: Business logic transformations and dimensional modeling
- **Production Layer**: Final analytics-ready tables and aggregations

**Key Schemas Available:**
- `staging.*` - Clean, standardized data from source systems
- `intermediate.*` - Dimensional models and fact tables 
- `prod.*` - Final analytics tables and aggregations

## Core Student Assessment Tables

### 1. Student Attendance & Demographics
**Table**: `intermediate.base_mid_end_comb_students_25_26_dim`
**Purpose**: Master student dimension table tracking attendance across assessment periods
**Key Columns**:
- `student_id` - Unique student identifier
- `baseline_attendence` - True/False for baseline assessment attendance
- `midline_attendence` - True/False for midline assessment attendance  
- `city_base`, `school_name_base`, `fellow_name_base` - Context from baseline
- `student_grade_base`, `donor_base` - Student grade and funding information

**Usage**: Use this table to count students who attended different assessment periods:
- Baseline attendance: `WHERE baseline_attendence = 'True'`
- Midline attendance: `WHERE midline_attendence = 'True'`

### 2. Student Assessment Scores
**Table**: `intermediate.base_mid_end_comb_scores_25_26_fct`
**Purpose**: Fact table containing detailed assessment scores across all periods
**Key Columns**:
- `student_id` - Links to student dimension table
- `rc_level_baseline_base`, `rc_level_midline_mid` - Reading Comprehension levels
- `rf_level_baseline_base`, `rf_level_midline_mid` - Reading Fluency levels  
- `math_level_baseline_base`, `math_level_midline_mid` - Math assessment levels
- `rc_assessed_perc_base`, `rc_assessed_perc_mid` - Assessment completion percentages

### 3. Assessment Completion Analytics
**Table**: `prod.assessment_completion_25_26`
**Purpose**: Aggregated view of assessment completion rates by city and grade
**Key Columns**:
- `city`, `grade` - Grouping dimensions
- `total_students_base`, `total_students_mid` - Student counts per assessment
- `assessed_students_rc_base`, `perc_comp_rc_base` - RC assessment completion
- `assessed_students_rf_base`, `perc_comp_rf_base` - RF assessment completion
- `assessed_students_math_base`, `perc_comp_math_base` - Math assessment completion

**Usage**: Pre-aggregated for dashboard metrics on assessment completion rates

## EcoChamps Program Tables

### 4. EcoChamps Student Data
**Table**: `staging.eco_student25_26_stg` 
**Purpose**: Student participation and session data for EcoChamps environmental program
**Key Columns**:
- `Roll No` - Student roll number (use for counting unique students)
- `School ID`, `School` - School identifiers
- `Chapter`, `District` - Geographic groupings
- `Donor Mapped` - Funding source (e.g., "CGI")

### 5. EcoChamps Session Planning
**Table**: `prod.plannedvsconducted_eco_25_26`
**Purpose**: Quarterly session planning vs actual execution for EcoChamps
**Key Columns**:
- `donor_mapped` - Funding source filter
- `school` - School-level breakdowns
- `q2_planned`, `q2_conducted` - Q2 session metrics
- `q3_planned`, `q3_conducted` - Q3 session metrics  
- `q4_planned`, `q4_conducted` - Q4 session metrics
- `planned_session`, `conducted_session` - Total session aggregates

## Academic Year Patterns

### AY 2024-25 Tables (24-25, 2425)
- `intermediate.base_mid_end_comb_students_2425_dim` - Student dimensions
- `prod.assessment_completion_2525` - Assessment completion (note: uses 2525 suffix)

### AY 2025-26 Tables (25-26)  
- `intermediate.base_mid_end_comb_students_25_26_dim` - Student dimensions
- `prod.assessment_completion_25_26` - Assessment completion

## Common Query Patterns

**Count students who attended baseline in AY 2025-26:**
```sql
SELECT COUNT(DISTINCT student_id) 
FROM intermediate.base_mid_end_comb_students_25_26_dim 
WHERE baseline_attendence = 'True'
```

**Count EcoChamps students for specific donor:**
```sql
SELECT COUNT(DISTINCT "Roll No") 
FROM staging.eco_student25_26_stg 
WHERE "Donor Mapped" = 'CGI'
```

**Assessment completion rates by city:**
```sql
SELECT city, grade, total_students_base, perc_comp_rc_base
FROM prod.assessment_completion_25_26
ORDER BY city, grade
```

## Table Discovery Tips
- Use `list_tables_by_keyword` with terms like: "students", "assessment", "eco", "completion"
- Always check `intermediate.*` tables for dimensional data
- Use `prod.*` tables for pre-calculated metrics and aggregations
- Staging tables contain granular transactional data

#### Key Educational Assessments

**Reading Comprehension (RC)**
- **Human Context:** How well students understand what they read
- **Metrics Tracked:**
  - RC Level (Developing, Beginner, Intermediate, Advanced)
  - RC Grade Level (reading at which grade level)
  - RC Status (overall performance category)
  - Factual understanding (%)
  - Inference skills (%)
  - Critical thinking (%)
  - Vocabulary knowledge (%)
  - Grammar skills (%)

**Reading Fluency (RF)** 
- **Human Context:** How smoothly and accurately students can read aloud
- **Metrics Tracked:**
  - RF Status (performance level)
  - RF Code (numerical assessment code)
  - RF % (overall reading fluency percentage)
  - Letter sounds recognition (%)
  - CVC words (Consonant-Vowel-Consonant simple words) (%)
  - Blends (combining letter sounds) (%)
  - Consonant diagraphs (ch, sh, th sounds) (%)
  - Magic E words (silent e patterns) (%)
  - Vowel diagraphs (ai, oa, ee sounds) (%)
  - Multi-syllable words (%)
  - Passage reading (Passage 1 & 2 scores) (%)

**Mathematics (Math)**
- **Human Context:** Student competency in fundamental math concepts
- **Metrics Tracked:**
  - Math Level (performance tier)
  - Math Status (overall category)
  - Math Mastery (overall percentage)
  - Numbers (basic number concepts) (%)
  - Patterns (recognizing sequences) (%)
  - Geometry (shapes and spatial reasoning) (%)
  - Mensuration (measurement) (%)
  - Time (time-related problems) (%)
  - Operations (addition, subtraction, etc.) (%)
  - Data Handling (charts, graphs interpretation) (%)

#### Assessment Timeline
- **Baseline:** Beginning of academic year assessment
- **Midline:** Mid-year progress check
- **Endline:** End of academic year final assessment

#### Organizational Structure
- **City:** Geographic location
- **PM (Program Manager):** Regional program supervisor
- **School:** Government school where program operates
- **Classroom ID:** Specific classroom identifier
- **Fellow:** Young volunteer teacher
- **Cohort:** Fellow training group
- **Grade:** Student class level (1-8 typically)
- **Student ID & Name:** Individual student tracking

### 2. EcoChamps Program (Environmental Education)
**What it is:** Part of BHUMI's Catalyze vertical, this environmental education program engages students in hands-on learning about sustainability, climate change, and environmental stewardship. The program combines theoretical knowledge with practical action-oriented modules.

**Data Collection Tools:** Google Sheets-based systems tracking student participation, module completion, and assessment scores

**Academic Year:** 2025-26

#### Environmental Modules
Students participate in hands-on learning modules:

- **Kitchen Garden:** Growing food sustainably, understanding plant cycles
- **Waste Management:** Proper disposal, recycling, reducing waste
- **Water Conservation:** Understanding water scarcity, conservation techniques  
- **Climate:** Climate change awareness, environmental impact
- **Lifestyle Choices:** Making environmentally conscious decisions

#### Assessment Structure
- **Baseline Score:** Initial environmental knowledge assessment
- **Endline Score:** Final knowledge assessment after modules
- **Module Attendance:** Participation tracking for each environmental topic
- **Modules Completed:** Total number of modules student finished
- **Modules Attendance %:** Overall participation rate

#### Program Tracking
- **Quarter System:** Academic year divided into Q1-Q4 for progress tracking
- **RAG (Red-Amber-Green) Status:** Traffic light system for program health monitoring
- **Planned vs Conducted:** Sessions planned versus actually delivered
- **Student Attendance:** Individual participation rates
- **Center Coordinators:** Local program managers (usually 2 per center)
- **Donor Mapping:** Funding source attribution for reporting

## Common Human-Friendly Terminology

### Performance Levels
- **Developing:** Student is building foundational skills
- **Beginner:** Student has basic skills but needs support
- **Intermediate:** Student demonstrates solid competency
- **Advanced:** Student exceeds grade-level expectations

### Attendance & Completion Tracking
- **Baseline/Midline/Endline Attendance:** Whether student was present for assessment
- **Assessment Completed:** Number of assessments student finished
- **Assessment Attendance %:** Student's overall participation rate in testing
- **Session Attendance:** Participation in regular program activities

### Geographic & Administrative
- **City:** Major urban area where program operates
- **Chapter:** Local BHUMI organizational unit
- **School ID:** Unique government school identifier
- **Roll No:** Student's official school enrollment number
- **Student Status:** Active, graduated, transferred, etc.
- **Donor Mapped/Funding:** Financial sponsor attribution for impact reporting

## Fellowship Data Pointers (AY 2025-26)
- **Active fellows (recommended count):** Use `prod.base_mid_end_comb_students_25_26_dim`. Count distinct fellow names where any attendance flag is true. Columns: `fellow_name_base`, `fellow_name_mid`, `baseline_attendence`, `midline_attendence`. A simple pattern is:
  - UNION the base and mid fellow names with their attendance flags, then `COUNT(DISTINCT fellow_name)` where attended is true.
- **Why this table:** It already combines baseline and midline sources (`baseline_25_26_stg`, `midline_25_26_stg`) so you don’t need separate joins.
- **Notes:** Prefer prod schema versions. Attendance flags are boolean; treat any true as “active this year.”

## Data Collection Tools & Methodology

**Primary Data Collection Platform:** Google Sheets
- **Fellowship Program:** Uses master Google Sheets for baseline, midline, and endline assessment data collection
  - 'Baseline 2024_Overall Analysis' sheet for AY 24-25 baseline data
  - 'Midline 2024_Overall Analysis' sheet for mid-year assessments
  - 'Endline 2025_Overall data' sheet for final assessments
- **EcoChamps Program:** Uses Google Sheets for student session data, attendance tracking, and assessment scores

**Assessment Methodology:**
- **Baseline-Midline-Endline Framework:** Systematic measurement of student progress over academic year
- **Standardized Metrics:** Consistent measurement across Reading Comprehension (RC), Reading Fluency (RF), and Mathematics
- **Attendance Tracking:** Digital recording of student participation in assessments and sessions
- **Quality Control:** Data validation and cleaning processes to ensure accuracy

**Data Quality Notes:**
- Multiple data sources require careful matching by Roll No, School ID, and Student Name
- Some assessments use "A" to indicate absent students (converted to 0 in analysis)
- Percentage values may include "%" symbol requiring cleanup
- Empty strings, "NA", and "Not Assessed" are normalized to null values
- Academic quarters run April-March (Indian academic calendar)
- RAG (Red-Amber-Green) parameters used for quarterly progress monitoring

## Impact Measurement
BHUMI tracks student growth over time by comparing baseline → midline → endline performance across all subjects, enabling measurement of educational impact and program effectiveness.
