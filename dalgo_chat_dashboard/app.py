import streamlit as st
import logging
import os
import sys
import time
import uuid
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
from db.chat_logger import ChatLogger
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
                    
                    # Initialize chat logger
                    st.session_state.chat_logger = ChatLogger(st.session_state.postgres_executor)
                    
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
            st.error(f"Initialization failed: {str(e)}")
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
    
    # Context Editor Button
    st.sidebar.subheader("Context Management")
    if st.sidebar.button("Edit Context File"):
        st.session_state.show_context_editor = True
    
    # Dashboard Selector
    if st.session_state.get('dashboard_graph'):
        dashboards = st.session_state.dashboard_graph.get('dashboards', {})
        if dashboards:
            st.sidebar.subheader("Dashboard Selection")
            
            # Create dashboard options
            dashboard_options = {}
            for dash_id, dash_data in dashboards.items():
                dash_obj = dash_data.get('dashboard')
                if dash_obj is not None and hasattr(dash_obj, 'title'):
                    dash_title = dash_obj.title
                elif dash_obj is not None and hasattr(dash_obj, 'dashboard_title'):
                    dash_title = dash_obj.dashboard_title
                else:
                    dash_title = dash_id
                dashboard_options[dash_title] = dash_id
            
            # Initialize default selection
            if 'selected_dashboard_id' not in st.session_state:
                st.session_state.selected_dashboard_id = list(dashboard_options.values())[0]
            
            # Dashboard dropdown
            current_title = None
            for title, dash_id in dashboard_options.items():
                if dash_id == st.session_state.selected_dashboard_id:
                    current_title = title
                    break
            
            selected_title = st.sidebar.selectbox(
                "Select Dashboard:",
                options=list(dashboard_options.keys()),
                index=list(dashboard_options.keys()).index(current_title) if current_title else 0,
                key="dashboard_selector"
            )
            
            # Update selected dashboard
            selected_dashboard_id = dashboard_options[selected_title]
            if selected_dashboard_id != st.session_state.selected_dashboard_id:
                st.session_state.selected_dashboard_id = selected_dashboard_id
                # Don't clear chat history - each dashboard will have its own
                st.rerun()
            
            # Show current dashboard info
            current_dashboard = dashboards[st.session_state.selected_dashboard_id]
            charts_list = current_dashboard.get('charts', [])
            st.sidebar.write(f"**Charts:** {len(charts_list)}")
            
        else:
            st.sidebar.write("No dashboards available")
            st.session_state.selected_dashboard_id = None
    else:
        st.sidebar.write("Loading dashboards...")
        st.session_state.selected_dashboard_id = None

def render_chat_interface():
    """Render the main chat interface"""
    st.title("Chat with Dashboards")
    ngo_name = st.session_state.get('ngo_name', 'Organization')
    st.caption(f"Ask questions about {ngo_name} program data and dashboards")

    composer = FinalAnswerComposer()

    # Initialize per-dashboard chat histories
    if "dashboard_chats" not in st.session_state:
        st.session_state.dashboard_chats = {}
    
    # Get chat history for current dashboard
    current_dashboard = st.session_state.get('selected_dashboard_id')
    if current_dashboard not in st.session_state.dashboard_chats:
        st.session_state.dashboard_chats[current_dashboard] = []
    
    # Set current chat history
    st.session_state.chat_history = st.session_state.dashboard_chats[current_dashboard]
    
    # Limit chat history size to prevent memory issues
    MAX_CHAT_HISTORY = 50
    if len(st.session_state.chat_history) > MAX_CHAT_HISTORY:
        st.session_state.chat_history = st.session_state.chat_history[-MAX_CHAT_HISTORY:]
    
    # Display chat history
    for i, message in enumerate(st.session_state.chat_history):
        with st.chat_message(message["role"]):
            st.write(message["content"])
            
            # Show additional info for assistant messages (ALWAYS show debug info)
            if message["role"] == "assistant" and "metadata" in message:
                metadata = message["metadata"]
                
                # Always show SQL queries as expandable section
                if metadata.get("sql_used"):
                    with st.expander("SQL Query"):
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
                    with st.expander("Results"):
                        st.code(sql_result["data_preview"], language="text")

                # Always show debug info - simplified approach
                if metadata.get("execution_info"):
                    with st.expander("Debug Info"):
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
            # Generate session ID if not exists
            if 'session_id' not in st.session_state:
                st.session_state.session_id = str(uuid.uuid4())
            
            start_time = time.time()
            
            with st.spinner("Thinking..."):
                try:
                    response = st.session_state.orchestrator.process_query(
                        user_query=prompt,
                        allow_retrieval=True,  # Always enabled
                        conversation_history=st.session_state.chat_history[-10:],  # Last 10 messages
                        selected_dashboard_id=st.session_state.get('selected_dashboard_id')
                    )

                    composed = composer.compose(response)
                    
                    # Display response
                    st.write(composed["text"])
                    if composed.get("table") is not None:
                        st.dataframe(composed["table"])
                    
                    # Show SQL and debug info for current response
                    if response.sql_used:
                        with st.expander("SQL Query"):
                            st.code(response.sql_used, language="sql")

                    if response.execution_info:
                        with st.expander("Debug Info"):
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
                                           height=200, key=f"current_tool_calls_{len(st.session_state.chat_history)}")
                            
                            # Show full debug JSON
                            st.text_area("Full Debug Info (copyable)", 
                                       str(info), 
                                       height=300, key=f"current_debug_info_{len(st.session_state.chat_history)}")
                    
                    # Prepare metadata for history
                    metadata = {
                        "sql_used": response.sql_used,
                        "sources_used": response.sources_used,
                        "chart_ids_used": response.chart_ids_used,
                        "dataset_ids_used": response.dataset_ids_used,
                        "execution_info": response.execution_info
                    }
                    
                    # Add assistant message to history
                    st.session_state.chat_history.append({
                        "role": "assistant", 
                        "content": composed["text"],
                        "metadata": metadata
                    })
                    
                    # Save back to dashboard-specific chat store
                    current_dashboard = st.session_state.get('selected_dashboard_id')
                    if current_dashboard:
                        st.session_state.dashboard_chats[current_dashboard] = st.session_state.chat_history
                    
                    # Log interaction asynchronously
                    if hasattr(st.session_state, 'chat_logger'):
                        response_time = int((time.time() - start_time) * 1000)
                        
                        st.session_state.chat_logger.log_interaction_async(
                            user_query=prompt,
                            assistant_response=composed["text"],
                            dashboard_id=st.session_state.get('selected_dashboard_id'),
                            sql_used=response.sql_used,
                            intent=response.execution_info.get('intent') if response.execution_info else None,
                            tool_calls=response.execution_info.get('tool_calls') if response.execution_info else None,
                            execution_info=response.execution_info,
                            sources_used=response.sources_used,
                            chart_ids_used=response.chart_ids_used,
                            dataset_ids_used=response.dataset_ids_used,
                            error_occurred=False,
                            response_time_ms=response_time,
                            session_id=st.session_state.session_id
                        )

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
                    
                    # Save back to dashboard-specific chat store
                    current_dashboard = st.session_state.get('selected_dashboard_id')
                    if current_dashboard:
                        st.session_state.dashboard_chats[current_dashboard] = st.session_state.chat_history
                    
                    # Log error interaction asynchronously
                    if hasattr(st.session_state, 'chat_logger'):
                        response_time = int((time.time() - start_time) * 1000)
                        
                        st.session_state.chat_logger.log_interaction_async(
                            user_query=prompt,
                            assistant_response=error_msg,
                            dashboard_id=st.session_state.get('selected_dashboard_id'),
                            sql_used=None,
                            intent=None,
                            tool_calls=None,
                            execution_info={"error": str(e)},
                            sources_used=None,
                            chart_ids_used=None,
                            dataset_ids_used=None,
                            error_occurred=True,
                            response_time_ms=response_time,
                            session_id=st.session_state.session_id
                        )
                

def render_context_editor():
    """Render the context file editor"""
    st.title("Context File Editor")
    ngo_name = st.session_state.get('ngo_name', 'Organization')
    st.caption(f"Edit the {ngo_name} context file that guides the AI's understanding")

    # Get context file path
    context_file_path = config.context_file_path
    
    try:
        # Read current context file
        if 'context_file_content' not in st.session_state:
            with open(context_file_path, 'r', encoding='utf-8') as f:
                st.session_state.context_file_content = f.read()
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.subheader("Context Content")
        
        with col2:
            # Refresh button to reload from file
            if st.button("Reload from File", help="Discard changes and reload from file"):
                try:
                    with open(context_file_path, 'r', encoding='utf-8') as f:
                        fresh_content = f.read()
                    st.session_state.context_file_content = fresh_content
                    st.session_state.context_file_modified = False
                    # Increment reload key to force text area refresh
                    st.session_state.context_reload_key += 1
                    st.success("Context reloaded from file - unsaved changes discarded")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to reload from file: {e}")
        
        # Text editor (use reload_key to force refresh when reloading from file)
        if 'context_reload_key' not in st.session_state:
            st.session_state.context_reload_key = 0
        
        edited_content = st.text_area(
            "Edit the context file content:",
            value=st.session_state.context_file_content,
            height=500,
            key=f"context_editor_{st.session_state.context_reload_key}",
            help="Changes are automatically saved to session state. Click 'Save & Apply Changes' to persist and reload system."
        )
        
        # Update session state when content changes
        if edited_content != st.session_state.context_file_content:
            st.session_state.context_file_content = edited_content
            st.session_state.context_file_modified = True
        
        # Save controls
        col1, col2 = st.columns([3, 1])
        
        with col1:
            save_button = st.button(
                "Save & Apply Changes", 
                type="primary",
                disabled=not st.session_state.get('context_file_modified', False),
                help="Save changes to disk and automatically reload the AI system"
            )
        
        with col2:
            # Show modification status
            if st.session_state.get('context_file_modified', False):
                st.warning("Unsaved changes")
            else:
                st.success("Saved")
        
        # Handle save button - automatically reload system after saving
        if save_button:
            try:
                # Save to file
                with open(context_file_path, 'w', encoding='utf-8') as f:
                    f.write(st.session_state.context_file_content)
                st.session_state.context_file_modified = False
                st.success("Context file saved successfully!")
                logger.info(f"Context file updated: {context_file_path}")
                
                # Automatically reload system context
                with st.spinner("Applying changes to AI system..."):
                    # Re-ingest documents with updated context
                    ingester = EnhancedDocumentIngester(config.ngo_context_folder)
                    documents = ingester.ingest_all()
                    
                    # Update vectorstore with new documents
                    if hasattr(st.session_state, 'vectorstore'):
                        st.session_state.vectorstore.ingest_documents(documents)
                    
                    # Update orchestrator with new context
                    if hasattr(st.session_state, 'orchestrator'):
                        st.session_state.orchestrator = EnhancedToolOrchestrator(
                            st.session_state.vectorstore,
                            st.session_state.schema_index,
                            st.session_state.postgres_executor,
                            config.context_file_path,
                            ingester.dbt_helper
                        )
                
                st.success("Changes applied successfully! Updated context is now active for new queries.")
                logger.info("System context automatically reloaded after file save")
                
                # Show doc counts
                doc_counts = {}
                for doc in documents:
                    t = doc.metadata.get("type", "unknown")
                    doc_counts[t] = doc_counts.get(t, 0) + 1
                
                st.info(f"Reloaded: {', '.join([f'{count} {type}' for type, count in doc_counts.items()])} documents")
                
            except Exception as e:
                st.error(f"Failed to save or apply changes: {e}")
                logger.error(f"Failed to save context file or reload system: {e}")
        
        # File stats
        st.subheader("File Information")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("File Size", f"{len(st.session_state.context_file_content):,} chars")
        
        with col2:
            lines = st.session_state.context_file_content.count('\n') + 1
            st.metric("Lines", f"{lines:,}")
        
        with col3:
            words = len(st.session_state.context_file_content.split())
            st.metric("Words", f"{words:,}")
    
    except FileNotFoundError:
        st.error(f"Context file not found: {context_file_path}")
    except Exception as e:
        st.error(f"Error loading context file: {e}")

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
    
    # Render sidebar first
    render_sidebar()
    
    # Show context editor if button was pressed, otherwise show chat
    if st.session_state.get('show_context_editor', False):
        # Add back button
        if st.button("← Back to Chat"):
            st.session_state.show_context_editor = False
            st.rerun()
        render_context_editor()
    else:
        # Normal chat interface
        render_chat_interface()
        
        # Show initialization status
        if not st.session_state.get('initialized', False):
            st.info("Initializing app components...")

if __name__ == "__main__":
    main()
