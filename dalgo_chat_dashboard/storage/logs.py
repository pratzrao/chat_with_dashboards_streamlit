import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import os

class ChatLogger:
    def __init__(self, log_dir: str = "storage/logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        
        # Setup file logging
        log_file = os.path.join(log_dir, f"chat_{datetime.now().strftime('%Y%m%d')}.log")
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        
        self.logger = logging.getLogger(__name__)
    
    def log_chat_turn(self, user_query: str, response_data: Dict[str, Any], 
                      execution_time_ms: float, session_id: str = "default"):
        """Log a complete chat turn with timing and metadata"""
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "user_query": user_query,
            "intent": response_data.get('execution_info', {}).get('intent'),
            "agent_used": response_data.get('execution_info', {}).get('agent'),
            "sql_used": response_data.get('sql_used'),
            "sources_used": response_data.get('sources_used', []),
            "chart_ids_used": response_data.get('chart_ids_used', []),
            "execution_time_ms": execution_time_ms,
            "response_length": len(response_data.get('response_text', '')),
            "success": 'error' not in response_data.get('execution_info', {})
        }
        
        # Log to structured file
        log_file = os.path.join(self.log_dir, f"chat_turns_{datetime.now().strftime('%Y%m%d')}.jsonl")
        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        # Log summary to standard logger
        self.logger.info(f"Turn: {user_query[:50]}... -> {response_data.get('execution_info', {}).get('agent')} ({execution_time_ms:.0f}ms)")
    
    def log_error(self, error: str, context: Dict[str, Any] = None):
        """Log errors with context"""
        error_entry = {
            "timestamp": datetime.now().isoformat(),
            "error": error,
            "context": context or {}
        }
        
        error_file = os.path.join(self.log_dir, f"errors_{datetime.now().strftime('%Y%m%d')}.jsonl")
        with open(error_file, 'a') as f:
            f.write(json.dumps(error_entry) + '\n')
        
        self.logger.error(f"Error: {error}")

# Global logger instance
chat_logger = ChatLogger()