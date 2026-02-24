import logging
import re
from typing import Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from agents.models import AgentResponse
from config import config

logger = logging.getLogger(__name__)

class ClarificationAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o-mini", 
            temperature=0.2,
            api_key=config.openai_api_key
        )
        
        with open("prompts/clarify.md", "r") as f:
            self.system_prompt = f.read()
    
    def ask_clarification(self, user_question: str, context_pack: Dict[str, Any], 
                         missing_info: List[str] = None) -> AgentResponse:
        """Generate clarification questions for ambiguous queries"""
        
        # Format context for the prompt
        context_str = self._format_context_pack(context_pack)
        
        prompt = self.system_prompt.replace("{context_pack}", context_str)
        prompt = prompt.replace("{user_question}", user_question)
        
        # Add missing info context if provided
        if missing_info:
            prompt += f"\n\nSpecific missing information identified: {', '.join(missing_info)}"
        
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"Ask clarifying questions for: {user_question}")
        ]
        
        try:
            response = self.llm.invoke(messages)
            response_text = response.content.strip()
            
            # Extract clarification questions
            clarification_questions = self._extract_questions(response_text)
            
            return AgentResponse(
                response_text=response_text,
                sql_used=None,
                sources_used=self._get_available_sources(context_pack),
                chart_ids_used=[],
                dataset_ids_used=[],
                execution_info={"agent": "clarification"},
                needs_clarification=True,
                clarification_questions=clarification_questions
            )
            
        except Exception as e:
            logger.error(f"Clarification error: {e}")
            return AgentResponse(
                response_text=self._fallback_clarification(user_question, missing_info),
                sources_used=[],
                chart_ids_used=[],
                dataset_ids_used=[],
                execution_info={"agent": "clarification", "error": str(e)},
                needs_clarification=True,
                clarification_questions=self._fallback_questions(missing_info)
            )
    
    def _format_context_pack(self, context_pack: Dict[str, Any]) -> str:
        """Format context pack for clarification prompt"""
        parts = []
        
        # List available charts
        charts = context_pack.get('retrieved', {}).get('charts', [])
        if charts:
            parts.append("**Available Charts:**")
            for chart in charts[:5]:  # Top 5
                metadata = chart.get('metadata', {})
                slice_name = metadata.get('slice_name', 'Unknown Chart')
                chart_id = metadata.get('chart_id', 'Unknown')
                parts.append(f"- {slice_name} (Chart {chart_id})")
        
        # List available time periods (from schema)
        schema_snippets = context_pack.get('schema_snippets', [])
        date_columns = []
        for snippet in schema_snippets:
            for col in snippet.get('columns', []):
                if 'date' in col['name'].lower() or col.get('type', '').lower() in ['timestamp', 'date']:
                    date_columns.append(col['name'])
        
        if date_columns:
            parts.append(f"\n**Available Date Columns:** {', '.join(set(date_columns))}")
        
        return "\n".join(parts)
    
    def _extract_questions(self, response_text: str) -> List[str]:
        """Extract individual clarification questions from response"""
        questions = []
        
        # Look for numbered lists
        lines = response_text.split('\n')
        for line in lines:
            line = line.strip()
            if re.match(r'^\d+\.', line) or line.startswith('- '):
                # Remove numbering/bullets
                question = re.sub(r'^\d+\.\s*', '', line)
                question = re.sub(r'^-\s*', '', question)
                if '?' in question:
                    questions.append(question.strip())
        
        # Fallback: find sentences ending with ?
        if not questions:
            sentences = re.split(r'[.!]', response_text)
            for sentence in sentences:
                if '?' in sentence:
                    questions.append(sentence.strip())
        
        return questions[:3]  # Max 3 questions
    
    def _get_available_sources(self, context_pack: Dict[str, Any]) -> List[str]:
        """Get list of available source IDs"""
        sources = []
        
        retrieved = context_pack.get('retrieved', {})
        for doc_type in ['charts', 'datasets', 'context']:
            for doc in retrieved.get(doc_type, []):
                sources.append(doc.get('doc_id', ''))
        
        return sources
    
    def _fallback_clarification(self, user_question: str, missing_info: List[str] = None) -> str:
        """Generate fallback clarification message"""
        base_msg = f"I need more details to answer '{user_question}' effectively."
        
        if missing_info:
            if 'time_range' in missing_info:
                base_msg += " What time period are you interested in?"
            if 'metric' in missing_info:
                base_msg += " Which specific metric would you like to see?"
            if 'dimension' in missing_info:
                base_msg += " How would you like the data broken down?"
        else:
            base_msg += " Could you provide more specific details about what you'd like to see?"
        
        return base_msg
    
    def _fallback_questions(self, missing_info: List[str] = None) -> List[str]:
        """Generate fallback clarification questions"""
        questions = []
        
        if missing_info:
            if 'time_range' in missing_info:
                questions.append("What time period are you interested in?")
            if 'metric' in missing_info:
                questions.append("Which specific metric would you like to see?")
            if 'dimension' in missing_info:
                questions.append("How would you like the data broken down?")
        else:
            questions.append("Could you provide more specific details about what you'd like to see?")
        
        return questions