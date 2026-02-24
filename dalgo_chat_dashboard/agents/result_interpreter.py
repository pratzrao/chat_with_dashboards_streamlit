import logging
import pandas as pd
from typing import Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from agents.models import AgentResponse, QueryResult
from config import config

logger = logging.getLogger(__name__)

class ResultInterpreter:
    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.3,
            api_key=config.openai_api_key
        )
        
        with open("prompts/interpret.md", "r") as f:
            self.system_prompt = f.read()
    
    def interpret_results(self, user_question: str, context_pack: Dict[str, Any], 
                         sql_query: str, query_result: QueryResult) -> AgentResponse:
        """Interpret SQL query results into a meaningful response"""
        
        if not query_result.success:
            return self._handle_sql_error(query_result.error, sql_query)
        
        # Format context and results for prompt
        context_str = self._format_context_pack(context_pack)
        results_str = self._format_query_results(query_result)
        
        prompt = self.system_prompt.replace("{context_pack}", context_str)
        prompt = prompt.replace("{user_question}", user_question)
        prompt = prompt.replace("{sql_query}", sql_query)
        prompt = prompt.replace("{query_results}", results_str)
        
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"Interpret these query results for the user.")
        ]
        
        try:
            response = self.llm.invoke(messages)
            response_text = response.content.strip()
            
            # Extract source references
            sources_used = self._extract_sources_from_context(context_pack)
            chart_ids = [chart.get('metadata', {}).get('chart_id') 
                        for chart in context_pack.get('retrieved', {}).get('charts', [])
                        if chart.get('metadata', {}).get('chart_id')]
            
            return AgentResponse(
                response_text=response_text,
                sql_used=sql_query,
                sources_used=sources_used,
                chart_ids_used=chart_ids,
                dataset_ids_used=[],
                execution_info={
                    "agent": "result_interpreter",
                    "row_count": query_result.row_count,
                    "execution_time_ms": query_result.execution_time_ms
                }
            )
            
        except Exception as e:
            logger.error(f"Result interpretation error: {e}")
            return self._fallback_interpretation(user_question, query_result, sql_query)
    
    def _format_context_pack(self, context_pack: Dict[str, Any]) -> str:
        """Format relevant context information"""
        parts = []
        
        # Add program context
        program_context = context_pack.get('retrieved', {}).get('context', [])
        if program_context:
            parts.append("**Program Context:**")
            for ctx in program_context[:2]:  # Top 2 context pieces
                content = ctx.get('content', '')[:300]  # Truncate
                parts.append(f"- {content}...")
        
        # Add chart context
        charts = context_pack.get('retrieved', {}).get('charts', [])
        if charts:
            parts.append("\n**Relevant Charts:**")
            for chart in charts[:3]:  # Top 3 charts
                metadata = chart.get('metadata', {})
                slice_name = metadata.get('slice_name', 'Unknown')
                chart_id = metadata.get('chart_id', '')
                parts.append(f"- {slice_name} (Chart {chart_id})")
        
        return "\n".join(parts)
    
    def _format_query_results(self, query_result: QueryResult) -> str:
        """Format query results for the prompt"""
        if not query_result.success:
            return f"Query failed: {query_result.error}"
        
        parts = [
            f"**Row Count:** {query_result.row_count}",
            f"**Execution Time:** {query_result.execution_time_ms}ms"
        ]
        
        if query_result.dataframe_preview:
            parts.append(f"**Data Preview:**\n{query_result.dataframe_preview}")
        
        return "\n".join(parts)
    
    def _extract_sources_from_context(self, context_pack: Dict[str, Any]) -> List[str]:
        """Extract source doc IDs from context pack"""
        sources = []
        retrieved = context_pack.get('retrieved', {})
        
        for doc_type in ['charts', 'datasets', 'context']:
            for doc in retrieved.get(doc_type, []):
                doc_id = doc.get('doc_id')
                if doc_id:
                    sources.append(doc_id)
        
        return sources
    
    def _handle_sql_error(self, error: str, sql_query: str) -> AgentResponse:
        """Handle SQL execution errors"""
        return AgentResponse(
            response_text=f"I encountered an error running the query: {error}",
            sql_used=sql_query,
            sources_used=[],
            chart_ids_used=[],
            dataset_ids_used=[],
            execution_info={"agent": "result_interpreter", "error": error}
        )
    
    def _fallback_interpretation(self, user_question: str, query_result: QueryResult, 
                               sql_query: str) -> AgentResponse:
        """Provide basic fallback interpretation"""
        if query_result.success:
            response_text = f"Query completed successfully with {query_result.row_count} results."
            if query_result.row_count == 0:
                response_text += " No data was found matching your criteria."
            elif query_result.row_count == config.max_limit:
                response_text += f" Results limited to {config.max_limit} rows."
        else:
            response_text = f"Query failed: {query_result.error}"
        
        return AgentResponse(
            response_text=response_text,
            sql_used=sql_query,
            sources_used=[],
            chart_ids_used=[],
            dataset_ids_used=[],
            execution_info={"agent": "result_interpreter", "fallback": True}
        )