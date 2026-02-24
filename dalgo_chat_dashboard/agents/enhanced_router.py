import json
import logging
import re
from typing import Dict, Any, List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agents.models import RouterResponse, IntentType, ConversationContext, FollowUpContext
from config import config

logger = logging.getLogger(__name__)

class EnhancedIntentRouter:
    """Enhanced intent router with conversation context and follow-up detection"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.0,
            api_key=config.openai_api_key,
            model_kwargs={"response_format": {"type": "json_object"}}
        )
        
    def classify_intent(
        self, 
        user_query: str, 
        conversation_history: List[Dict[str, Any]] = None
    ) -> RouterResponse:
        """Classify intent with conversation context awareness"""
        
        # Import here to avoid circular import
        from agents.conversation_manager import ConversationManager
        
        # Extract conversation context
        conv_manager = ConversationManager()
        conv_context = conv_manager.extract_conversation_context(conversation_history or [])
        
        # Use LLM for complex classification
        return self._llm_classification(user_query, conv_context)
    
    
    def _heuristic_classification(self, query: str, context: ConversationContext) -> Optional[RouterResponse]:
        """Fast heuristic classification for obvious cases"""
        q = query.lower().strip()
        tokens = re.findall(r"\b[\w']+\b", q)
        
        # Small talk
        greetings = {"hi", "hey", "hello", "gm", "good morning", "thanks", "thank you"}
        token_set = set(tokens)
        if token_set and token_set.issubset(greetings) and len(tokens) <= 4:
            return RouterResponse(
                intent=IntentType.SMALL_TALK,
                confidence=0.95,
                reason="Greeting or social pleasantry"
            )

        # Mission/vision/organization questions should not be flagged irrelevant
        org_terms = {"mission", "vision", "bhumi", "organization", "org", "ngo"}
        if any(t in org_terms for t in tokens):
            return RouterResponse(
                intent=IntentType.QUERY_WITHOUT_SQL,
                confidence=0.8,
                reason="Organizational info request (mission/vision/context)",
                force_tool_usage=False,
            )
        
        # Obvious follow-up patterns (if we have previous context)
        if context.last_sql_query or context.last_chart_ids:
            follow_up_indicators = [
                "now", "also", "same but", "split by", "break down", "filter to", 
                "only", "exclude", "by district", "by month", "by chapter",
                "last quarter", "this month", "weekly", "daily"
            ]
            if any(indicator in q for indicator in follow_up_indicators):
                return RouterResponse(
                    intent=IntentType.FOLLOW_UP_SQL,
                    confidence=0.9,
                    reason="Follow-up query detected with previous SQL context",
                    force_tool_usage=True,
                    follow_up_context=FollowUpContext(
                        is_follow_up=True,
                        reusable_elements={
                            "previous_sql": context.last_sql_query,
                            "previous_tables": context.last_tables_used,
                            "previous_chart_ids": context.last_chart_ids
                        }
                    )
                )
        
        return None  # Use LLM for complex cases
    
    def _llm_classification(self, query: str, context: ConversationContext) -> RouterResponse:
        """Use LLM for complex intent classification with conversation awareness"""
        
        system_prompt = self._build_system_prompt(context)
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Classify this query: {query}")
        ]
        
        try:
            response = self.llm.invoke(messages)
            result_text = response.content.strip()
            
            # Parse JSON response
            try:
                result_data = json.loads(result_text)
                return RouterResponse(**result_data)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse router JSON: {result_text}")
                return self._fallback_classification(query)
                
        except Exception as e:
            logger.error(f"LLM router error: {e}")
            return self._fallback_classification(query)
    
    def _build_system_prompt(self, context: ConversationContext) -> str:
        """Build system prompt with conversation context"""
        
        # Load the enhanced router prompt
        try:
            with open("prompts/enhanced_router.md", "r") as f:
                base_prompt = f.read()
        except FileNotFoundError:
            # Fallback to inline prompt
            base_prompt = """You are an intent classifier for NGO dashboard queries. 
            
Your job is to analyze the user's query and return a JSON response with the intent classification.

Available intents:
- "query_with_sql": User wants data/numbers (counts, trends, breakdowns) 
- "query_without_sql": User wants explanations (metric definitions, chart info, methodology)
- "follow_up_sql": User wants to modify a previous data query (add dimension, filter, timeframe)
- "follow_up_context": User wants more explanation about previous results
- "needs_clarification": Query is too vague or ambiguous
- "small_talk": Greetings, thanks, general chat
- "irrelevant": Off-topic or out of scope

Return JSON in this exact format:
{
  "intent": "query_with_sql",
  "confidence": 0.85,
  "reason": "User asking for count data",
  "force_tool_usage": true
}

Guidelines:
- Set force_tool_usage=true for any data questions (query_with_sql, follow_up_sql)"""
        
        # Add conversation context if available
        if context.last_sql_query or context.last_chart_ids:
            context_info = f"""

CONVERSATION CONTEXT:
- Previous SQL: {context.last_sql_query or 'None'}
- Previous tables: {', '.join(context.last_tables_used) or 'None'}  
- Previous charts: {', '.join(context.last_chart_ids) or 'None'}
- Last response type: {context.last_response_type or 'None'}

Use this context to detect follow-up queries that want to modify or expand on previous results.
"""
            base_prompt += context_info
            
        return base_prompt
    
    def _fallback_classification(self, query: str) -> RouterResponse:
        """Simple fallback when LLM classification fails"""
        q = query.lower()
        
        # Data query keywords
        if any(keyword in q for keyword in ["how many", "count", "total", "trend", "show me", "breakdown", "compare"]):
            intent = IntentType.QUERY_WITH_SQL
            force_tools = True
            reason = "Contains data analysis keywords"
        # Definition/explanation keywords  
        elif any(keyword in q for keyword in ["what does", "how is calculated", "explain", "definition", "which dataset"]):
            intent = IntentType.QUERY_WITHOUT_SQL
            force_tools = False
            reason = "Contains explanation keywords"
        # Vague queries
        elif any(keyword in q for keyword in ["performance", "doing", "issues", "problems"]):
            intent = IntentType.NEEDS_CLARIFICATION
            force_tools = False
            reason = "Query too vague"
        else:
            intent = IntentType.QUERY_WITHOUT_SQL
            force_tools = False
            reason = "Default classification"
            
        return RouterResponse(
            intent=intent,
            confidence=0.7,
            reason=reason,
            force_tool_usage=force_tools
        )
