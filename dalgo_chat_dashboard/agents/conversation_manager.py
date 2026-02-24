import re
import json
import logging
from typing import Dict, Any, List, Optional
from agents.models import ConversationContext

logger = logging.getLogger(__name__)

class ConversationManager:
    """Manages conversation state and context extraction for follow-up queries"""
    
    def __init__(self):
        self.max_history_turns = 10
    
    def extract_conversation_context(self, chat_history: List[Dict[str, Any]]) -> ConversationContext:
        """Extract conversation context from chat history for follow-up detection"""
        
        context = ConversationContext()
        
        # Look through recent assistant responses for SQL and metadata
        recent_history = chat_history[-self.max_history_turns:] if chat_history else []
        
        for message in reversed(recent_history):
            if message.get("role") != "assistant":
                continue
                
            metadata = message.get("metadata", {})
            
            # Extract SQL context (most recent SQL query)
            if metadata.get("sql_used") and not context.last_sql_query:
                context.last_sql_query = metadata["sql_used"]
                context.last_tables_used = self._extract_tables_from_sql(metadata["sql_used"])
                context.last_response_type = "sql_result"
                
                # Extract metrics and dimensions from SQL
                context.last_metrics = self._extract_metrics_from_sql(metadata["sql_used"])
                context.last_dimensions = self._extract_dimensions_from_sql(metadata["sql_used"])
                context.last_filters = self._extract_filters_from_sql(metadata["sql_used"])
            
            # Extract chart context
            if metadata.get("chart_ids_used") and not context.last_chart_ids:
                context.last_chart_ids = [str(cid) for cid in metadata["chart_ids_used"]]
                if not context.last_response_type:
                    context.last_response_type = "metadata_answer"
            
            # If we have both SQL and chart context, we can stop
            if context.last_sql_query and context.last_chart_ids:
                break
        
        return context
    
    def _extract_tables_from_sql(self, sql: str) -> List[str]:
        """Extract table names from SQL query"""
        if not sql:
            return []
        
        tables = []
        # Match patterns like "FROM table_name" or "FROM schema.table_name" 
        patterns = [
            r'\bFROM\s+([`"]?)(\w+\.\w+)\1',  # schema.table
            r'\bFROM\s+([`"]?)(\w+)\1',       # table_name
            r'\bJOIN\s+([`"]?)(\w+\.\w+)\1',  # JOIN schema.table
            r'\bJOIN\s+([`"]?)(\w+)\1'        # JOIN table
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, sql, re.IGNORECASE)
            for match in matches:
                table_name = match[1] if isinstance(match, tuple) else match
                if table_name not in tables:
                    tables.append(table_name)
        
        return tables
    
    def _extract_metrics_from_sql(self, sql: str) -> List[str]:
        """Extract metric expressions from SQL SELECT clause"""
        if not sql:
            return []
        
        metrics = []
        # Find SELECT clause
        select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
        if select_match:
            select_clause = select_match.group(1)
            
            # Extract aggregation functions
            agg_patterns = [
                r'COUNT\s*\(\s*([^)]+)\s*\)',
                r'SUM\s*\(\s*([^)]+)\s*\)',
                r'AVG\s*\(\s*([^)]+)\s*\)',
                r'MIN\s*\(\s*([^)]+)\s*\)',
                r'MAX\s*\(\s*([^)]+)\s*\)'
            ]
            
            for pattern in agg_patterns:
                matches = re.findall(pattern, select_clause, re.IGNORECASE)
                metrics.extend(matches)
        
        return metrics[:5]  # Limit to avoid noise
    
    def _extract_dimensions_from_sql(self, sql: str) -> List[str]:
        """Extract GROUP BY dimensions from SQL"""
        if not sql:
            return []
        
        group_by_match = re.search(r'GROUP\s+BY\s+([^ORDER|LIMIT|;]+)', sql, re.IGNORECASE)
        if group_by_match:
            group_clause = group_by_match.group(1).strip()
            # Split by comma and clean up
            dimensions = [dim.strip().strip('`"') for dim in group_clause.split(',')]
            return dimensions
        
        return []
    
    def _extract_filters_from_sql(self, sql: str) -> List[str]:
        """Extract WHERE clause filters from SQL"""
        if not sql:
            return []
        
        filters = []
        where_match = re.search(r'WHERE\s+(.+?)(?:GROUP|ORDER|LIMIT|$)', sql, re.IGNORECASE | re.DOTALL)
        if where_match:
            where_clause = where_match.group(1).strip()
            
            # Extract simple filter patterns
            filter_patterns = [
                r"(\w+)\s*=\s*'([^']+)'",     # column = 'value'
                r"(\w+)\s*=\s*(\w+)",         # column = value
                r"(\w+)\s+IN\s*\([^)]+\)"     # column IN (...)
            ]
            
            for pattern in filter_patterns:
                matches = re.findall(pattern, where_clause, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple) and len(match) >= 2:
                        filters.append(f"{match[0]} = {match[1]}")
                    else:
                        filters.append(str(match))
        
        return filters[:3]  # Limit to avoid noise
    
    def build_follow_up_context_prompt(self, base_context: ConversationContext, user_query: str) -> str:
        """Build additional context for follow-up queries"""
        
        context_parts = [
            "PREVIOUS QUERY CONTEXT:",
            f"Last SQL: {base_context.last_sql_query or 'None'}",
            f"Tables used: {', '.join(base_context.last_tables_used) or 'None'}",
            f"Metrics: {', '.join(base_context.last_metrics) or 'None'}",
            f"Dimensions: {', '.join(base_context.last_dimensions) or 'None'}",
            f"Filters: {', '.join(base_context.last_filters) or 'None'}",
            "",
            f"NEW INSTRUCTION: {user_query}",
            "",
            "TASK: Modify the previous query based on the new instruction. Reuse tables and context where possible."
        ]
        
        return "\n".join(context_parts)
    
    def detect_sql_modification_type(self, user_query: str) -> str:
        """Detect what type of SQL modification is requested"""
        
        query_lower = user_query.lower()
        
        # Dimension modification
        dimension_keywords = ["by", "split by", "break down", "breakdown", "group by", "grouped by"]
        if any(keyword in query_lower for keyword in dimension_keywords):
            return "add_dimension"
        
        # Filter modification
        filter_keywords = ["filter", "only", "just", "exclude", "where", "for"]
        if any(keyword in query_lower for keyword in filter_keywords):
            return "add_filter"
        
        # Time modification
        time_keywords = ["last", "this", "previous", "next", "monthly", "weekly", "quarterly", "daily"]
        if any(keyword in query_lower for keyword in time_keywords):
            return "modify_timeframe"
        
        # Aggregation change
        agg_keywords = ["total", "sum", "count", "average", "avg", "maximum", "minimum"]
        if any(keyword in query_lower for keyword in agg_keywords):
            return "change_aggregation"
        
        return "general_modification"
    
    def suggest_follow_up_tools(self, modification_type: str, base_context: ConversationContext) -> List[str]:
        """Suggest which tools to use for different follow-up types"""
        
        if modification_type == "add_filter" and base_context.last_tables_used:
            # Will need distinct values for new filter
            return ["get_distinct_values", "run_sql_query"]
        
        elif modification_type == "add_dimension" and base_context.last_tables_used:
            # Will need schema to confirm column exists
            return ["get_schema_snippets", "run_sql_query"]
        
        elif modification_type in ["modify_timeframe", "change_aggregation"]:
            # Can likely reuse previous table context
            return ["run_sql_query"]
        
        else:
            # General case - might need retrieval
            return ["retrieve_docs", "get_schema_snippets", "run_sql_query"]