import streamlit as st
import logging
from retrieval.multi_context_loader import MultiContextLoader
from retrieval.enhanced_ingest import EnhancedDocumentIngester
from config import config

logger = logging.getLogger(__name__)

def render_multi_context_editor():
    """Render the multi-file context editor"""
    st.title("Context Files Editor")
    ngo_name = st.session_state.get('ngo_name', 'Organization')
    st.caption(f"Edit the {ngo_name} organizational and dashboard-specific context files")

    # Initialize multi-context loader
    try:
        multi_context_loader = MultiContextLoader(config.ngo_context_folder)
        contexts = multi_context_loader.load_all_contexts()
    except Exception as e:
        st.error(f"Error initializing context loader: {e}")
        return
    
    # Create tabs for different context files
    tab_labels = ["Organization"]
    
    # Add tabs for dashboard contexts
    dashboard_ids = list(contexts.dashboard_contexts.keys())
    current_dashboard_id = st.session_state.get('selected_dashboard_id')
    
    # Ensure current dashboard is in the list if it exists
    if current_dashboard_id and current_dashboard_id not in dashboard_ids:
        dashboard_ids.append(current_dashboard_id)
    
    for dashboard_id in dashboard_ids:
        tab_labels.append(f"{dashboard_id.replace('_', ' ').title()}")
    
    tabs = st.tabs(tab_labels)
    
    # Organization Context Tab
    with tabs[0]:
        _render_org_context_editor(multi_context_loader, contexts)
    
    # Dashboard Context Tabs
    for i, dashboard_id in enumerate(dashboard_ids):
        with tabs[i + 1]:
            _render_dashboard_context_editor(multi_context_loader, dashboard_id, contexts)
    
def _render_org_context_editor(multi_context_loader, contexts):
    """Render the organizational context editor"""
    st.subheader("Organizational Context")
    st.caption("High-level information about the organization, programs, and general context")
    
    # Initialize session state for org context
    if 'org_context_content' not in st.session_state:
        st.session_state.org_context_content = contexts.org_context
        st.session_state.org_context_modified = False
    
    # Content editor
    edited_content = st.text_area(
        "Edit organizational context:",
        value=st.session_state.org_context_content,
        height=400,
        key="org_context_editor",
        help="This context is always included for all dashboards"
    )
    
    # Track changes
    if edited_content != st.session_state.org_context_content:
        st.session_state.org_context_content = edited_content
        st.session_state.org_context_modified = True
    
    # Save button
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        if st.button("Save Organization Context", 
                    type="primary",
                    disabled=not st.session_state.get('org_context_modified', False)):
            if _save_and_reload_context(multi_context_loader, 'org', st.session_state.org_context_content):
                st.session_state.org_context_modified = False
                st.success("Organization context saved and applied!")
    
    with col2:
        if st.button("Reload"):
            contexts_fresh = multi_context_loader.load_all_contexts()
            st.session_state.org_context_content = contexts_fresh.org_context
            st.session_state.org_context_modified = False
            st.success("Reloaded from file")
            st.rerun()
    
    with col3:
        if st.session_state.get('org_context_modified', False):
            st.warning("Unsaved")
        else:
            st.success("Saved")
    
    # File info
    _show_file_info("Organization Context", st.session_state.org_context_content)

def _render_dashboard_context_editor(multi_context_loader, dashboard_id, contexts):
    """Render dashboard-specific context editor"""
    st.subheader(f"{dashboard_id.replace('_', ' ').title()} Context")
    st.caption(f"Specific context for the {dashboard_id} dashboard")
    
    # Get dashboard context content
    dashboard_content = contexts.dashboard_contexts.get(dashboard_id, "")
    
    # Check if file exists
    file_exists = multi_context_loader.dashboard_context_exists(dashboard_id)
    
    if not file_exists:
        st.info(f"Dashboard context file for '{dashboard_id}' doesn't exist yet.")
        if st.button(f"Create {dashboard_id} Context File"):
            if multi_context_loader.create_dashboard_context(dashboard_id):
                st.success(f"Created context file for {dashboard_id}")
                st.rerun()
            else:
                st.error("Failed to create context file")
        return
    
    # Initialize session state for this dashboard
    session_key = f'dashboard_context_{dashboard_id}'
    session_modified_key = f'{session_key}_modified'
    
    if session_key not in st.session_state:
        st.session_state[session_key] = dashboard_content
        st.session_state[session_modified_key] = False
    
    # Content editor
    edited_content = st.text_area(
        f"Edit {dashboard_id} context:",
        value=st.session_state[session_key],
        height=400,
        key=f"dashboard_context_editor_{dashboard_id}",
        help="This context is included only when this dashboard is selected"
    )
    
    # Track changes
    if edited_content != st.session_state[session_key]:
        st.session_state[session_key] = edited_content
        st.session_state[session_modified_key] = True
    
    # Save button
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        if st.button(f"Save {dashboard_id} Context", 
                    type="primary",
                    disabled=not st.session_state.get(session_modified_key, False),
                    key=f"save_dashboard_{dashboard_id}"):
            if _save_and_reload_context(multi_context_loader, dashboard_id, st.session_state[session_key]):
                st.session_state[session_modified_key] = False
                st.success(f"{dashboard_id} context saved and applied!")
    
    with col2:
        if st.button("Reload", key=f"reload_dashboard_{dashboard_id}"):
            contexts_fresh = multi_context_loader.load_all_contexts()
            fresh_content = contexts_fresh.dashboard_contexts.get(dashboard_id, "")
            st.session_state[session_key] = fresh_content
            st.session_state[session_modified_key] = False
            st.success("Reloaded from file")
            st.rerun()
    
    with col3:
        if st.session_state.get(session_modified_key, False):
            st.warning("Unsaved")
        else:
            st.success("Saved")
    
    # Show file info
    _show_file_info(f"{dashboard_id} Context", st.session_state[session_key])

def _save_and_reload_context(multi_context_loader, context_type, content):
    """Save context and reload the system"""
    try:
        # Save the context
        if context_type == 'org':
            success = multi_context_loader.save_org_context(content)
        else:
            success = multi_context_loader.save_dashboard_context(context_type, content)
        
        if not success:
            st.error("Failed to save context file")
            return False
        
        # Reload system context
        with st.spinner("Applying changes to AI system..."):
            # Update orchestrator context if it exists
            if hasattr(st.session_state, 'orchestrator'):
                # Force reload of context in orchestrator
                current_dashboard = st.session_state.get('selected_dashboard_id')
                st.session_state.orchestrator._update_dashboard_context(current_dashboard)
            
            # Re-ingest documents with updated context
            if hasattr(st.session_state, 'vectorstore'):
                ingester = EnhancedDocumentIngester(config.ngo_context_folder)
                documents = ingester.ingest_all()
                st.session_state.vectorstore.ingest_documents(documents)
        
        return True
        
    except Exception as e:
        st.error(f"Error saving and reloading context: {e}")
        logger.error(f"Context save/reload error: {e}")
        return False

def _show_file_info(title, content):
    """Show file statistics"""
    with st.expander(f"{title} Statistics"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Characters", f"{len(content):,}")
        
        with col2:
            lines = content.count('\n') + 1 if content else 0
            st.metric("Lines", f"{lines:,}")
        
        with col3:
            words = len(content.split()) if content else 0
            st.metric("Words", f"{words:,}")
