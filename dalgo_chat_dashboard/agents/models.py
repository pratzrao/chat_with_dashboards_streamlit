from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from enum import Enum

class IntentType(str, Enum):
    NEEDS_CLARIFICATION = "needs_clarification"
    SMALL_TALK = "small_talk"
    FOLLOW_UP_SQL = "follow_up_sql"          # NEW: Follow-up requiring SQL modification
    FOLLOW_UP_CONTEXT = "follow_up_context"  # NEW: Follow-up requiring context only
    IRRELEVANT = "irrelevant"
    QUERY_WITH_SQL = "query_with_sql"
    QUERY_WITHOUT_SQL = "query_without_sql"

class ConversationContext(BaseModel):
    """Context extracted from conversation history"""
    last_sql_query: Optional[str] = None
    last_tables_used: List[str] = []
    last_chart_ids: List[str] = []
    last_metrics: List[str] = []
    last_dimensions: List[str] = []
    last_filters: List[str] = []
    last_response_type: Optional[str] = None  # "sql_result" | "metadata_answer"
    
class FollowUpContext(BaseModel):
    """Follow-up specific context"""
    is_follow_up: bool
    follow_up_type: Optional[str] = None  # "modify_dimension" | "modify_filter" | "modify_timeframe" | "expand_context"
    reusable_elements: Dict[str, Any] = {}
    modification_instruction: Optional[str] = None

class RouterResponse(BaseModel):
    intent: IntentType
    confidence: float
    reason: str
    missing_info: List[str] = []
    follow_up_context: Optional[FollowUpContext] = None
    force_tool_usage: bool = False

class SqlPlan(BaseModel):
    tables: List[str]
    joins: List[Dict[str, str]] = []
    filters: List[Dict[str, Any]] = []
    group_by: List[str] = []
    metrics: List[Dict[str, str]] = []
    order_by: List[Dict[str, str]] = []
    limit: int = 500
    notes: str = ""

class SqlValidationResult(BaseModel):
    is_valid: bool
    corrected_sql: Optional[str] = None
    errors: List[str] = []
    warnings: List[str] = []

class QueryResult(BaseModel):
    success: bool
    dataframe_preview: Optional[str] = None
    row_count: int = 0
    execution_time_ms: Optional[float] = None
    error: Optional[str] = None
    sql_used: str = ""

class AgentResponse(BaseModel):
    response_text: str
    sql_used: Optional[str] = None
    sources_used: List[str] = []
    chart_ids_used: List[int] = []
    dataset_ids_used: List[str] = []
    execution_info: Dict[str, Any] = {}
    needs_clarification: bool = False
    clarification_questions: List[str] = []