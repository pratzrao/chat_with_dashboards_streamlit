# CGI Donor Report Dashboard Context

## Program Overview
This dashboard tracks metrics and analytics specifically for the CGI donor-funded EcoChamps program in the 2025-26 academic year. EcoChamps is BHUMI's environmental education initiative that engages students in sustainability practices and environmental awareness activities.

## Key Terminology

**EcoChamps Program**: BHUMI's environmental education initiative focused on creating environmental awareness and sustainable practices among students. Part of the larger "Catalyze" vertical focusing on civic projects.

**CGI (Capgemini Group)**: Corporate partner and donor supporting the EcoChamps environmental education program. This dashboard specifically tracks CGI-funded activities and beneficiaries.

**Environmental Sessions**: Structured educational sessions focused on environmental topics like sustainability, conservation, waste management, and climate awareness.

**Planned vs Conducted Sessions**: 
- **Planned Sessions**: Number of environmental education sessions scheduled to be conducted
- **Conducted Sessions**: Actual number of sessions completed, indicating program execution efficiency

**Donor Mapping**: The process of attributing students, schools, and activities to specific donor funding, allowing for donor-specific impact tracking.

**Chapter-wise Distribution**: Geographic distribution of activities across BHUMI's various city chapters where the program operates.

## Metrics Explanation

**Student Count (CGI)**: Total number of unique students participating in CGI-funded EcoChamps activities. Measured by distinct Roll Numbers to avoid double counting.

**School Count (CGI)**: Number of distinct schools where CGI-funded EcoChamps activities are conducted. Measured by unique School IDs.

**Session Metrics**:
- **Planned Sessions**: Target number of environmental education sessions to be delivered
- **Conducted Sessions**: Actual sessions delivered, indicating program execution rate
- **Session Completion Rate**: Conducted/Planned ratio showing program delivery effectiveness

**Chapter Distribution**: Geographic spread of program activities showing reach across different BHUMI operational areas.

## Data Interpretation Guidelines

**Impact Measurement**:
- Student and school counts show the direct reach and scale of CGI's investment
- Session metrics indicate program execution quality and efficiency
- Chapter-wise data shows geographic distribution and local impact

**Donor Reporting**:
- All metrics are filtered specifically for CGI-funded activities
- Data supports accountability and impact reporting to the donor
- Helps demonstrate return on investment and program effectiveness

**Program Management**:
- Planned vs conducted sessions help identify operational challenges
- Geographic distribution aids in resource allocation decisions
- Student engagement metrics support program improvement

## Program Context

**Environmental Focus Areas**:
- Sustainability education and practices
- Waste management and recycling
- Climate change awareness
- Conservation activities
- Green initiatives in schools

**Academic Year**: 2025-26 represents the current program cycle for CGI-funded activities.

**Integration with Education**: EcoChamps sessions are often integrated with regular curriculum to reinforce environmental concepts through practical activities.

## Important Notes

**Data Sources**: 
- Student data tracked through staging tables with donor mapping
- Session data maintained in production systems for real-time tracking
- Roll Numbers and School IDs ensure unique counting without duplication

**Donor Specificity**: All data shown is filtered for "Donor Mapped = CGI" ensuring accurate attribution of impact to CGI funding.

**Program Quality**: The focus is not just on quantity (number of students/schools) but also on quality (session completion rates, engagement levels).

**Sustainability Impact**: The ultimate goal is behavior change and environmental consciousness among participants, measured through both quantitative metrics and qualitative assessments.

## EcoChamps Program Data Tables

### EcoChamps Student Data
**Table**: `staging.eco_student25_26_stg` 
**Purpose**: Student participation and session data for EcoChamps environmental program
**Key Columns**:
- `Roll No` - Student roll number (use for counting unique students)
- `School ID`, `School` - School identifiers
- `Chapter`, `District` - Geographic groupings
- `Donor Mapped` - Funding source (e.g., "CGI")

### EcoChamps Session Planning
**Table**: `prod.plannedvsconducted_eco_25_26`
**Purpose**: Quarterly session planning vs actual execution for EcoChamps
**Key Columns**:
- `donor_mapped` - Funding source filter
- `school` - School-level breakdowns
- `q2_planned`, `q2_conducted` - Q2 session metrics
- `q3_planned`, `q3_conducted` - Q3 session metrics  
- `q4_planned`, `q4_conducted` - Q4 session metrics
- `planned_session`, `conducted_session` - Total session aggregates

## Environmental Program Components

### Environmental Modules
Students participate in hands-on learning modules:

- **Kitchen Garden**: Growing food sustainably, understanding plant cycles
- **Waste Management**: Proper disposal, recycling, reducing waste
- **Water Conservation**: Understanding water scarcity, conservation techniques  
- **Climate**: Climate change awareness, environmental impact
- **Lifestyle Choices**: Making environmentally conscious decisions

### Assessment Structure
- **Baseline Score**: Initial environmental knowledge assessment
- **Endline Score**: Final knowledge assessment after modules
- **Module Attendance**: Participation tracking for each environmental topic
- **Modules Completed**: Total number of modules student finished
- **Modules Attendance %**: Overall participation rate

### Program Tracking
- **Quarter System**: Academic year divided into Q1-Q4 for progress tracking
- **RAG (Red-Amber-Green) Status**: Traffic light system for program health monitoring
- **Planned vs Conducted**: Sessions planned versus actually delivered
- **Student Attendance**: Individual participation rates
- **Center Coordinators**: Local program managers (usually 2 per center)
- **Donor Mapping**: Funding source attribution for reporting

## Common Query Examples

**Count EcoChamps students for CGI donor:**
```sql
SELECT COUNT(DISTINCT "Roll No") 
FROM staging.eco_student25_26_stg 
WHERE "Donor Mapped" = 'CGI'
```

**Session completion analysis:**
```sql
SELECT school, planned_session, conducted_session,
       (conducted_session::float / planned_session) * 100 as completion_rate
FROM prod.plannedvsconducted_eco_25_26
WHERE donor_mapped = 'CGI'
```