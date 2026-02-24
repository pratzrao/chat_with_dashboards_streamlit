import logging
from typing import Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from agents.models import AgentResponse
from config import config

logger = logging.getLogger(__name__)

class NonSqlAnswerAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.3,
            api_key=config.openai_api_key
        )
        
        with open("prompts/nonsql.md", "r") as f:
            self.system_prompt = f.read()
    
    def answer_question(self, user_question: str, context_pack: Dict[str, Any]) -> AgentResponse:
        """Answer question using retrieved context without SQL"""
        
        # Format context for the prompt
        context_str = self._format_context_pack(context_pack)
        
        prompt = self.system_prompt.replace("{context_pack}", context_str)
        prompt = prompt.replace("{user_question}", user_question)
        
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"Answer this question using the provided context: {user_question}")
        ]
        
        try:
            response = self.llm.invoke(messages)
            response_text = response.content.strip()
            
            # Extract sources from response if present
            sources_used, chart_ids, dataset_ids = self._extract_sources(response_text, context_pack)
            
            return AgentResponse(
                response_text=response_text,
                sql_used=None,
                sources_used=sources_used,
                chart_ids_used=chart_ids,
                dataset_ids_used=dataset_ids,
                execution_info={"agent": "nonsql_answer"},
                needs_clarification=False
            )
            
        except Exception as e:
            logger.error(f"Non-SQL answer error: {e}")
            return AgentResponse(
                response_text=f"I encountered an error while processing your question: {str(e)}",
                sources_used=[],
                chart_ids_used=[],
                dataset_ids_used=[],
                execution_info={"agent": "nonsql_answer", "error": str(e)}
            )
    
    def _format_context_pack(self, context_pack: Dict[str, Any]) -> str:
        """Format context pack for the prompt"""
        parts = []
        
        # Add retrieved charts
        if context_pack.get('retrieved', {}).get('charts'):
            parts.append("**Charts Context:**")
            for chart in context_pack['retrieved']['charts']:
                content = chart.get('content', '')
                doc_id = chart.get('doc_id', '')
                parts.append(f"{doc_id}: {content}")
        
        # Add retrieved datasets
        if context_pack.get('retrieved', {}).get('datasets'):
            parts.append("\n**Datasets Context:**")
            for dataset in context_pack['retrieved']['datasets']:
                content = dataset.get('content', '')
                doc_id = dataset.get('doc_id', '')
                parts.append(f"{doc_id}: {content}")
        
        # Add program context
        if context_pack.get('retrieved', {}).get('context'):
            parts.append("\n**Program Context:**")
            for context in context_pack['retrieved']['context']:
                content = context.get('content', '')
                doc_id = context.get('doc_id', '')
                parts.append(f"{doc_id}: {content}")
        
        return "\n".join(parts) if parts else "No context available"
    
    def _extract_sources(self, response_text: str, context_pack: Dict[str, Any]) -> tuple[List[str], List[int], List[str]]:
        """Extract source references from the response"""
        sources_used = []
        chart_ids = []
        dataset_ids = []
        
        # Look for explicit source mentions in response
        retrieved = context_pack.get('retrieved', {})
        
        for chart in retrieved.get('charts', []):
            doc_id = chart.get('doc_id', '')
            if doc_id in response_text:
                sources_used.append(doc_id)
                chart_id = chart.get('metadata', {}).get('chart_id')
                if chart_id:
                    chart_ids.append(chart_id)
        
        for dataset in retrieved.get('datasets', []):
            doc_id = dataset.get('doc_id', '')
            if doc_id in response_text:
                sources_used.append(doc_id)
                dataset_id = dataset.get('metadata', {}).get('dataset_id')
                if dataset_id:
                    dataset_ids.append(dataset_id)
        
        for context in retrieved.get('context', []):
            doc_id = context.get('doc_id', '')
            if doc_id in response_text:
                sources_used.append(doc_id)
        
        # If no explicit sources found, use top retrieved items
        if not sources_used:
            if retrieved.get('charts'):
                sources_used.append(retrieved['charts'][0].get('doc_id', ''))
                chart_id = retrieved['charts'][0].get('metadata', {}).get('chart_id')
                if chart_id:
                    chart_ids.append(chart_id)
        
        return sources_used, chart_ids, dataset_ids