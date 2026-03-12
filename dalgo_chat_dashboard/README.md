# Chat with Dashboards

Production-ready Streamlit application for conversational analytics powered by LangChain agents and PostgreSQL data warehouses.

## Features

- 🤖 **Multi-agent orchestration** with specialized SQL and retrieval agents
- 📊 **Chart-first data discovery** using dashboard metadata  
- 🔒 **SQL safety guards** with PII detection and query validation
- 🗣️ **Natural language queries** with follow-up conversation support
- 📈 **Real-time data visualization** with automatic chart generation
- 🔧 **Production deployment ready** with comprehensive error handling
- 🔑 **Streamlit Cloud compatible** with SSH tunnel support
- 📁 **Multi-context system** with organizational + dashboard-specific contexts
- 🎯 **Dashboard-aware access control** restricts data access by current dashboard
- 🔍 **Intelligent error handling** with cross-dashboard query suggestions

## Setup

### 1. Install Dependencies
```bash
cd dalgo_chat_dashboard
pip install -r requirements.txt
```

### 2. Configure Environment

#### Option A: Streamlit Secrets (Recommended for Production)
Create `.streamlit/secrets.toml`:
```toml
OPENAI_API_KEY = "your-openai-key"
PG_HOST = "localhost"
PG_DATABASE = "your-database"  
PG_USER = "your-user"
PG_PASSWORD = "your-password"
NGO_CONTEXT_FOLDER = "../bhumi_context"
```

#### Option B: Environment Variables (Development)
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Required configuration:
- `OPENAI_API_KEY`: Your OpenAI API key
- `PG_HOST`, `PG_PORT`, `PG_DATABASE`, `PG_USER`, `PG_PASSWORD`: Postgres connection
- `NGO_CONTEXT_FOLDER`: Path to context data (defaults to `../bhumi_context`)

**Configuration Priority**: Streamlit secrets → Environment variables → Defaults

### 3. Run the Application
```bash
streamlit run app.py
```

The app will:
1. Initialize the vector store with dashboard metadata
2. Connect to the Postgres database
3. Load dbt models and schema information
4. Start the chat interface at `http://localhost:8501`

## Usage

### Query Types

**Data Analysis Questions (SQL)**:
- "How many students attended baseline assessments this year?"
- "Show me reading comprehension trends by city"
- "Top 10 schools by assessment completion rate"
- "Compare EcoChamps session completion by quarter"

**Explanation Questions (No SQL)**:
- "What does 'Reading Fluency' assessment measure?"
- "How is assessment completion rate calculated?"
- "Which DBT model powers the student assessment data?"
- "Explain the Fellowship program structure"

**Follow-up Questions**:
- "Now filter to Chennai"
- "Same thing but by grade level"
- "Break that down by Fellow"

## Architecture

### Components

#### Core Orchestration
- **Tool Orchestrator** (`agents/enhanced_tool_orchestrator.py`): Central engine managing LLM + function calling for retrieval, dbt model search/lineage/details, schema snippets, distinct values, and guarded SQL with follow-up support.
- **Intent Router** (`agents/enhanced_router.py`): JSON intent classifier with conversation context; forces tool usage for data questions.

#### Context & Access Control  
- **Multi-Context System** (`retrieval/multi_context_loader.py`): Loads organizational context + dashboard-specific contexts dynamically.
- **Dashboard Allowlist** (`retrieval/dashboard_allowlist.py`): Restricts table access based on current dashboard's charts and DBT upstream dependencies.
- **Intelligent Error Detection** (`agents/dashboard_relevance_detector.py`): Analyzes failed queries and suggests relevant dashboards.

#### Data & Retrieval
- **Retrieval Layer** (`retrieval/enhanced_ingest.py`, `retrieval/vectorstore.py`): Ingests BHUMI charts/datasets/context/dbt docs into Chroma with semantic search.
- **DBT Helpers** (`db/dbt_helpers.py`): Model lineage and schema information from dbt artifacts.
- **SQL Safety** (`agents/sql_guard.py`): Read-only enforcement, forbidden keyword checks, LIMIT injection.

#### User Interface
- **UI Layer** (`app.py`): Streamlit chat with SQL/source expanders and dashboard selection.
- **Multi-Context Editor** (`ui/multi_context_editor.py`): Tabbed interface for editing organizational and dashboard-specific contexts.

### Data Sources
- **Dashboard Exports**: Organization dashboard/chart/dataset JSON/YAML metadata (`bhumi_context/dashboard_json/charts.json`)
- **DBT Artifacts**: `manifest.json`, `catalog.json` for data lineage (`bhumi_context/bhumi_dbt/`)
- **Multi-Context Files**: 
  - Organizational context (`bhumi_context/org_context.md`)
  - Dashboard-specific contexts (`bhumi_context/dashboard_contexts/*.md`) 
- **Live Database**: Read-only PostgreSQL connection for data queries (allowed schemas: `prod`, `dev_prod`, `staging`, `intermediate`)

## Safety Features

- **Read-only Access**: Only SELECT queries allowed
- **Query Validation**: Blocks DDL/DML operations and multi-statement queries  
- **PII Protection**: Detects and masks potential personally identifiable information
- **Resource Limits**: Query timeouts, row limits, schema restrictions
- **Dashboard Access Control**: Users only see tables relevant to current dashboard
- **Comprehensive SQL Injection Prevention**: Validates CTEs, subqueries, dynamic SQL, and union operations
- **Audit Logging**: All queries and responses logged with metadata

## File Structure

```
dalgo_chat_dashboard/
├── app.py                  # Main Streamlit application 
├── config.py               # Environment configuration
├── requirements.txt        # Python dependencies
├── agents/
│   ├── enhanced_tool_orchestrator.py  # Central orchestration engine
│   ├── enhanced_router.py              # Intent classification
│   ├── dashboard_relevance_detector.py # Cross-dashboard error analysis
│   ├── conversation_manager.py         # Chat history management
│   ├── sql_guard.py                    # SQL safety validation
│   └── models.py                       # Data structures
├── retrieval/
│   ├── multi_context_loader.py         # Multi-context system
│   ├── dashboard_allowlist.py          # Dashboard access control
│   ├── enhanced_ingest.py              # Document ingestion
│   ├── vectorstore.py                  # ChromaDB management
│   ├── ngo_context_loader.py           # Legacy context loader
│   └── bhumi_parser.py                 # Dashboard/chart parsing
├── ui/
│   └── multi_context_editor.py         # Context editing interface
├── db/
│   ├── dbt_helpers.py                  # DBT model utilities
│   ├── postgres.py                     # Database connection
│   ├── ssh_tunnel.py                   # Secure connectivity
│   └── chat_logger.py                  # Query audit logging
├── prompts/                            # System prompts for agents
├── storage/                            # Chroma DB persistence
└── manual_testing.md                   # Manual test script

bhumi_context/                          # Multi-context data
├── org_context.md                      # Organizational context
├── dashboard_contexts/                 # Dashboard-specific contexts
│   ├── fellowship_school_app_25_26.md
│   ├── cgi_donor_report.md
│   └── fellowship_comparison.md
├── dashboard_json/
│   └── charts.json                     # Dashboard/chart definitions
└── bhumi_dbt/                          # DBT artifacts
    ├── manifest.json
    └── catalog.json
```

## Deployment

### Local Development
- Uses `.env` file or `.streamlit/secrets.toml`
- Supports SSH tunneling for remote databases

### Streamlit Cloud/Production
- Uses `.streamlit/secrets.toml` exclusively
- Configure secrets in Streamlit Cloud dashboard
- Automatic HTTPS and scaling
- SSH tunnel support for private databases

### Docker Deployment
```dockerfile
# Use secrets.toml for containerized deployments
COPY .streamlit/secrets.toml /app/.streamlit/secrets.toml
```

## Security Notes

- Both `.env` and `.streamlit/secrets.toml` are gitignored
- API keys and passwords never committed to version control
- SQL queries validated and sanitized before execution
- Read-only database access enforced
- SSH private keys handled securely via Streamlit secrets
