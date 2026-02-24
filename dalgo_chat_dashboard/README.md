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
- **Enhanced Tool Orchestrator** (`agents/enhanced_tool_orchestrator.py`): LLM + function calling for retrieval, dbt model search/lineage/details, schema snippets, distinct values, and guarded SQL with follow-up support.
- **Enhanced Intent Router** (`agents/enhanced_router.py`): JSON intent classifier with conversation context; forces tool usage for data questions.
- **Retrieval Layer** (`retrieval/enhanced_ingest.py`, `retrieval/vectorstore.py`): Ingests BHUMI charts/datasets/context/dbt docs into Chroma with a lightweight hash embedding.
- **DBT Helpers** (`db/dbt_helpers.py`): Model lineage and schema information from dbt artifacts.
- **SQL Safety** (`agents/sql_guard.py`): Read-only enforcement, forbidden keyword checks, LIMIT injection.
- **UI Layer** (`app.py`): Streamlit chat with SQL/source expanders and retrieval toggle.

### Data Sources
- **Dashboard Exports**: Organization dashboard/chart/dataset JSON/YAML metadata
- **DBT Artifacts**: `manifest.json`, `catalog.json` for data lineage
- **Human Context**: Organization-specific program documentation
- **Live Database**: Read-only PostgreSQL connection for data queries

## Safety Features

- **Read-only Access**: Only SELECT queries allowed
- **Query Validation**: Blocks DDL/DML operations and multi-statement queries  
- **PII Protection**: Detects and masks potential personally identifiable information
- **Resource Limits**: Query timeouts, row limits, schema restrictions
- **Audit Logging**: All queries and responses logged with metadata

## File Structure

```
dalgo_chat_dashboard/
├── app.py                  # Main Streamlit application (enhanced stack)
├── config.py               # Environment configuration
├── requirements.txt        # Python dependencies
├── db/
│   ├── dbt_helpers.py      # DBT model and lineage utilities
│   └── postgres.py         # Database connection and execution
├── retrieval/
│   ├── enhanced_ingest.py  # Ingest BHUMI exports + context + dbt
│   ├── ngo_context_loader.py
│   ├── superset_parser.py
│   └── vectorstore.py      # ChromaDB vector store management
├── agents/
│   ├── enhanced_tool_orchestrator.py
│   ├── enhanced_router.py
│   ├── conversation_manager.py
│   ├── sql_guard.py
│   └── models.py
├── prompts/                # System prompts for agents
├── storage/                # Chroma DB persistence
├── manual_testing.md       # Manual test script
└── bhumi_context/          # Context, dbt artifacts, dashboard exports
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
