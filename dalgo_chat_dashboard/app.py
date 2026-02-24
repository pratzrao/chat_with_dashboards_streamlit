import streamlit as st
import logging
import os
import sys
from typing import Dict, Any, List
import pandas as pd

# Add current directory to Python path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import config
from agents.answer_composer import FinalAnswerComposer
from retrieval.vectorstore import VectorStore
from db.dbt_helpers import DbtHelper
from db.postgres import PostgresExecutor, SchemaIndex
from db.ssh_tunnel import create_tunnel
from agents.enhanced_tool_orchestrator import EnhancedToolOrchestrator
from retrieval.enhanced_ingest import EnhancedDocumentIngester

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def initialize_app():
    """Initialize all app components"""
    if 'initialized' not in st.session_state:
        try:
            # Initialize components (show progress but don't keep messages)
            if 'tunnel' not in st.session_state:
                st.session_state.tunnel = create_tunnel()
                tunnel_placeholder = st.empty()
                with tunnel_placeholder:
                    with st.spinner("Establishing SSH tunnel..."):
                        if not st.session_state.tunnel.start():
                            st.error("Failed to establish SSH tunnel")
                            return
                tunnel_placeholder.empty()
            
            # Initialize components
            components_placeholder = st.empty()
            with components_placeholder:
                with st.spinner("Initializing components..."):
                    st.session_state.postgres_executor = PostgresExecutor()
                    st.session_state.schema_index = SchemaIndex(st.session_state.postgres_executor)
                    
                    # Initialize enhanced ingester and vector store  
                    ingester = EnhancedDocumentIngester(config.ngo_context_folder)
                    documents = ingester.ingest_all()
                    
                    # Track doc counts by type for display
                    doc_counts = {}
                    for doc in documents:
                        t = doc.metadata.get("type", "unknown")
                        doc_counts[t] = doc_counts.get(t, 0) + 1
                    st.session_state.doc_counts = doc_counts
                    
                    st.session_state.vectorstore = VectorStore()
                    st.session_state.vectorstore.ingest_documents(documents)
                    
                    # Initialize enhanced orchestrator  
                    st.session_state.orchestrator = EnhancedToolOrchestrator(
                        st.session_state.vectorstore,
                        st.session_state.schema_index,
                        st.session_state.postgres_executor,
                        config.context_file_path,
                        ingester.dbt_helper
                    )
                    
                    # Load dashboard context graph
                    st.session_state.dashboard_graph = ingester.get_dashboard_context_graph()
                    st.session_state.ngo_name = ingester.ngo_context.ngo_name
                    
                    # Test database connection
                    if st.session_state.postgres_executor.test_connection():
                        st.session_state.db_connected = True
                        logger.info("Database connection successful")
                    else:
                        st.session_state.db_connected = False
                        logger.error("Database connection failed")
            components_placeholder.empty()
            
            st.session_state.initialized = True
            
        except Exception as e:
            st.error(f"❌ Initialization failed: {str(e)}")
            st.session_state.initialized = False
            logger.error(f"App initialization error: {e}")

def render_sidebar():
    """Render the sidebar with controls"""
    st.sidebar.title("Dashboard Controls")
    
    # Connection status
    if st.session_state.get('db_connected', False):
        st.sidebar.success("🟢 Database Connected")
    else:
        st.sidebar.error("🔴 Database Disconnected")
        st.sidebar.info("Credentials: dalgo_airbyte_user@dalgo_warehouse")
        st.sidebar.info("SSH tunnel should be active on :15432")
    
    # NGO Context (BHUMI only)
    st.sidebar.subheader("NGO Context")
    current_ngo = st.session_state.get('ngo_name', 'BHUMI')
    st.sidebar.write(f"Organization: **{current_ngo}**")
    
    # No settings section needed anymore
    
    # Show dashboard info
    if st.session_state.get('dashboard_graph'):
        dashboards = st.session_state.dashboard_graph.get('dashboards', {})
        if dashboards:
            dash_id, dash_data = next(iter(dashboards.items()))
            st.session_state.dashboard_id = dash_id
            dash_obj = dash_data.get('dashboard')
            if dash_obj is not None and hasattr(dash_obj, 'title'):
                dash_title = dash_obj.title
            elif dash_obj is not None and hasattr(dash_obj, 'dashboard_title'):
                dash_title = dash_obj.dashboard_title
            else:
                dash_title = dash_id
            st.sidebar.subheader("Current Dashboard")
            st.sidebar.write(f"**{dash_title}**")
            charts_list = dash_data.get('charts', [])
            st.sidebar.write(f"Charts: {len(charts_list)}")
        else:
            st.sidebar.write("No dashboard loaded")
            st.session_state.dashboard_id = None
    else:
        st.sidebar.write("Loading dashboard...")
        st.session_state.dashboard_id = None

def render_chat_interface():
    """Render the main chat interface"""
    st.title("💬 Chat with Dashboards")
    ngo_name = st.session_state.get('ngo_name', 'Organization')
    st.caption(f"Ask questions about {ngo_name} program data and dashboards")

    composer = FinalAnswerComposer()

    # Initialize chat history with size limit
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    
    # Limit chat history size to prevent memory issues
    MAX_CHAT_HISTORY = 50
    if len(st.session_state.chat_history) > MAX_CHAT_HISTORY:
        st.session_state.chat_history = st.session_state.chat_history[-MAX_CHAT_HISTORY:]
    
    # Display chat history
    for i, message in enumerate(st.session_state.chat_history):
        with st.chat_message(message["role"]):
            st.write(message["content"])
            
            # Show additional info for assistant messages (only if not already displayed)
            if message["role"] == "assistant" and "metadata" in message:
                metadata = message["metadata"]
                
                # Skip if already displayed in current response
                if metadata.get("already_displayed"):
                    continue
                
                # Always show SQL queries as expandable section
                if metadata.get("sql_used"):
                    with st.expander("🔍 SQL Query"):
                        st.code(metadata["sql_used"], language="sql")

                # Results expander
                exec_info = metadata.get("execution_info") or {}
                sql_result = exec_info.get("sql_result") or {}
                rows = sql_result.get("rows") or []
                cols = sql_result.get("columns") or []
                if rows and cols:
                    import pandas as pd
                    st.dataframe(pd.DataFrame(rows, columns=cols))
                elif sql_result.get("data_preview"):
                    with st.expander("📊 Results"):
                        st.code(sql_result["data_preview"], language="text")

                # Always show debug info - simplified approach
                if metadata.get("execution_info"):
                    with st.expander("🐛 Debug Info"):
                        info = metadata.get("execution_info") or {}
                        
                        st.write("**Intent:**", info.get("intent", "Unknown"))
                        if info.get("turns"):
                            st.write("**Processing Turns:**", info.get("turns"))
                        if info.get("tool_calls"):
                            st.write("**Tool Calls:**", len(info.get("tool_calls", [])))
                            
                        # Show tool calls in a copyable format
                        if info.get("tool_calls"):
                            st.text_area("Tool Calls (copyable)", 
                                       str(info.get("tool_calls")), 
                                       height=200, key=f"hist_tool_calls_{i}")
                        
                        # Show full debug JSON
                        st.text_area("Full Debug Info (copyable)", 
                                   str(info), 
                                   height=300, key=f"hist_debug_info_{i}")
    
    # Chat input with BHUMI-specific examples
    ngo_name = st.session_state.get('ngo_name', 'organization')
    examples = {
        'BHUMI': "Ask about student assessments, EcoChamps program, session data...",
        'SHOFCO': "Ask about gender program, case data, survivor support...",
    }
    placeholder = examples.get(ngo_name, "Ask about the program data...")
    
    if prompt := st.chat_input(placeholder):
        if not st.session_state.get('initialized', False):
            st.error(f"App not initialized. Please wait for {ngo_name} context to load completely.")
            return
        
        # Add user message to history
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        
        # Display user message
        with st.chat_message("user"):
            st.write(prompt)
        
        # Process with orchestrator
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    response = st.session_state.orchestrator.process_query(
                        user_query=prompt,
                        allow_retrieval=True,  # Always enabled
                        conversation_history=st.session_state.chat_history[-10:]  # Last 10 messages
                    )

                    composed = composer.compose(response)
                    
                    # Display response
                    st.write(composed["text"])
                    if composed.get("table") is not None:
                        st.dataframe(composed["table"])
                    
                    # IMMEDIATELY show SQL and debug info for current response
                    # Always show SQL queries as expandable section
                    if response.sql_used:
                        with st.expander("🔍 SQL Query"):
                            st.code(response.sql_used, language="sql")

                    # Always show debug info - simplified approach
                    if response.execution_info:
                        with st.expander("🐛 Debug Info"):
                            info = response.execution_info
                            
                            st.write("**Intent:**", info.get("intent", "Unknown"))
                            if info.get("turns"):
                                st.write("**Processing Turns:**", info.get("turns"))
                            if info.get("tool_calls"):
                                st.write("**Tool Calls:**", len(info.get("tool_calls", [])))
                                
                            # Show tool calls in a copyable format
                            if info.get("tool_calls"):
                                st.text_area("Tool Calls (copyable)", 
                                           str(info.get("tool_calls")), 
                                           height=200, key=f"tool_calls_{len(st.session_state.chat_history)}")
                            
                            # Show full debug JSON
                            st.text_area("Full Debug Info (copyable)", 
                                       str(info), 
                                       height=300, key=f"debug_info_{len(st.session_state.chat_history)}")
                    
                    # Prepare metadata for history
                    metadata = {
                        "sql_used": response.sql_used,
                        "sources_used": response.sources_used,
                        "chart_ids_used": response.chart_ids_used,
                        "dataset_ids_used": response.dataset_ids_used,
                        "execution_info": response.execution_info,
                        "already_displayed": True  # Flag to skip duplicate display in history
                    }
                    
                    # Add assistant message to history
                    st.session_state.chat_history.append({
                        "role": "assistant", 
                        "content": composed["text"],
                        "metadata": metadata
                    })

                except Exception as e:
                    error_msg = "I'm having trouble processing your request. Please try rephrasing your question or check if the system is running properly."
                    st.error(error_msg)
                    logger.error(f"Query processing error: {e}")
                    
                    # Add error to chat history for context
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": error_msg,
                        "metadata": {"error": True}
                    })

def main():
    """Main Streamlit app"""
    st.set_page_config(
        page_title="Chat with Dashboards",
        page_icon="💬",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Initialize app components
    initialize_app()
    
    # Render UI
    render_sidebar()
    render_chat_interface()
    
    # Show initialization status
    if not st.session_state.get('initialized', False):
        st.info("🔄 Initializing app components...")

if __name__ == "__main__":
    main()
