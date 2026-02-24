from typing import Dict, Any, List, Optional
import streamlit as st

class SessionStore:
    """Manage Streamlit session state for chat functionality"""
    
    @staticmethod
    def get_conversation_history() -> List[Dict[str, str]]:
        """Get conversation history from session state"""
        return st.session_state.get('chat_history', [])
    
    @staticmethod
    def add_message(role: str, content: str, metadata: Dict[str, Any] = None):
        """Add a message to conversation history"""
        if 'chat_history' not in st.session_state:
            st.session_state.chat_history = []
        
        message = {
            "role": role,
            "content": content
        }
        
        if metadata:
            message["metadata"] = metadata
        
        st.session_state.chat_history.append(message)
    
    @staticmethod
    def get_last_sql_summary() -> Optional[str]:
        """Get summary of last SQL query executed"""
        return st.session_state.get('last_sql_summary')
    
    @staticmethod
    def set_last_sql_summary(summary: str):
        """Set summary of last SQL query"""
        st.session_state.last_sql_summary = summary
    
    @staticmethod
    def get_selected_dashboard_id() -> Optional[str]:
        """Get currently selected dashboard ID"""
        return st.session_state.get('dashboard_id')
    
    @staticmethod
    def clear_history():
        """Clear conversation history"""
        if 'chat_history' in st.session_state:
            del st.session_state.chat_history
    
    @staticmethod
    def get_session_config() -> Dict[str, Any]:
        """Get current session configuration"""
        return {
            'strict_mode': st.session_state.get('strict_mode', True),
            'show_debug': st.session_state.get('show_debug', False),
            'selected_dashboard': st.session_state.get('dashboard_id'),
            'messages_count': len(st.session_state.get('chat_history', []))
        }