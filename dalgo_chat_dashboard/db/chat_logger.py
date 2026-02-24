import logging
import threading
import json
from datetime import datetime
from typing import Optional, Dict, Any
from db.postgres import PostgresExecutor

logger = logging.getLogger(__name__)

class ChatLogger:
    """Async chat interaction logger for PostgreSQL"""
    
    def __init__(self, postgres_executor: PostgresExecutor):
        self.postgres_executor = postgres_executor
        self._ensure_schema_exists()
        
    def _ensure_schema_exists(self):
        """Create chat_logs schema and table if not exists"""
        try:
            # Test database connection first
            if not self.postgres_executor.test_connection():
                logger.error("Database connection failed - cannot create chat_logs schema")
                return
            
            # Create schema synchronously for better error handling
            self.postgres_executor.execute(
                "CREATE SCHEMA IF NOT EXISTS chat_logs"
            )
            
            # Create table
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS chat_logs.interactions (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT NOW(),
                session_id VARCHAR(255),
                dashboard_id VARCHAR(255),
                user_query TEXT NOT NULL,
                assistant_response TEXT NOT NULL,
                sql_used TEXT,
                intent VARCHAR(100),
                tool_calls JSONB,
                execution_info JSONB,
                sources_used JSONB,
                chart_ids_used JSONB,
                dataset_ids_used JSONB,
                error_occurred BOOLEAN DEFAULT FALSE,
                response_time_ms INTEGER,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """
            self.postgres_executor.execute(create_table_sql)
            
            # Create index for performance
            self.postgres_executor.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_logs_timestamp ON chat_logs.interactions(timestamp)"
            )
            self.postgres_executor.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_logs_dashboard ON chat_logs.interactions(dashboard_id)"
            )
            
            logger.info("Chat logs schema and table created successfully")
            
        except Exception as e:
            logger.error(f"Failed to create chat logs schema: {e}")
            # Don't raise - allow app to continue without logging
    
    def log_interaction_async(
        self,
        user_query: str,
        assistant_response: str,
        dashboard_id: Optional[str] = None,
        sql_used: Optional[str] = None,
        intent: Optional[str] = None,
        tool_calls: Optional[list] = None,
        execution_info: Optional[Dict[str, Any]] = None,
        sources_used: Optional[list] = None,
        chart_ids_used: Optional[list] = None,
        dataset_ids_used: Optional[list] = None,
        error_occurred: bool = False,
        response_time_ms: Optional[int] = None,
        session_id: Optional[str] = None
    ):
        """Log chat interaction asynchronously"""
        
        def _log():
            try:
                insert_sql = """
                INSERT INTO chat_logs.interactions (
                    session_id, dashboard_id, user_query, assistant_response,
                    sql_used, intent, tool_calls, execution_info,
                    sources_used, chart_ids_used, dataset_ids_used,
                    error_occurred, response_time_ms
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                
                params = (
                    session_id,
                    dashboard_id,
                    user_query,
                    assistant_response,
                    sql_used,
                    intent,
                    json.dumps(tool_calls) if tool_calls else None,
                    json.dumps(execution_info) if execution_info else None,
                    json.dumps(sources_used) if sources_used else None,
                    json.dumps(chart_ids_used) if chart_ids_used else None,
                    json.dumps(dataset_ids_used) if dataset_ids_used else None,
                    error_occurred,
                    response_time_ms
                )
                
                self.postgres_executor.execute(insert_sql, params)
                logger.debug(f"Logged interaction for dashboard {dashboard_id}")
                
            except Exception as e:
                logger.error(f"Failed to log interaction: {e}")
                # Don't raise - logging failure shouldn't break user experience
        
        # Start background thread for logging
        threading.Thread(target=_log, daemon=True).start()
    
    def get_recent_interactions(self, limit: int = 50, dashboard_id: Optional[str] = None):
        """Get recent chat interactions (for debugging/analysis)"""
        try:
            where_clause = ""
            params = []
            
            if dashboard_id:
                where_clause = "WHERE dashboard_id = %s"
                params.append(dashboard_id)
            
            sql = f"""
            SELECT 
                timestamp,
                dashboard_id,
                user_query,
                assistant_response,
                sql_used,
                intent,
                error_occurred,
                response_time_ms
            FROM chat_logs.interactions
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT %s
            """
            params.append(limit)
            
            return self.postgres_executor.execute_query(sql, params)
            
        except Exception as e:
            logger.error(f"Failed to retrieve interactions: {e}")
            return []