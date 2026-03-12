import json
import uuid
import logging
import re
from typing import List, Dict, Any, Optional, TypedDict

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    HumanMessage,
    SystemMessage, 
    AIMessage,
    ToolMessage,
)
from langchain_core.messages.tool import ToolCall
from types import SimpleNamespace
from openai import OpenAI
from langgraph.graph import StateGraph, START, END

from agents.models import AgentResponse, ConversationContext
from agents.enhanced_router import EnhancedIntentRouter
from agents.conversation_manager import ConversationManager
from agents.sql_guard import SqlGuard
from db.postgres import PostgresExecutor, SchemaIndex
from db.dbt_helpers import DbtHelper
from retrieval.vectorstore import VectorStore
from retrieval.dashboard_allowlist import DashboardTableAllowlist
from retrieval.multi_context_loader import MultiContextLoader
from agents.dashboard_relevance_detector import DashboardRelevanceDetector
from config import config

logger = logging.getLogger(__name__)

class EnhancedToolOrchestrator:
    """
    Enhanced tool orchestrator with reliable tool usage and follow-up support.
    
    Key improvements:
    1. Uses tool_choice="required" to force tool calls for data queries
    2. Handles conversation context for follow-ups  
    3. Enforces get_distinct_values before WHERE clauses on text columns
    4. Simplified flow: let LLM call whatever tools it needs
    """
    
    def __init__(
        self,
        vectorstore: VectorStore,
        schema_index: SchemaIndex,
        postgres_executor: PostgresExecutor,
        ngo_context_folder: str,
        dbt_helper: Optional[DbtHelper] = None,
    ):
        self.vectorstore = vectorstore
        self.schema_index = schema_index
        self.postgres = postgres_executor
        self.dbt_helper = dbt_helper
        self.router = EnhancedIntentRouter()
        self.conversation_manager = ConversationManager()
        self.dashboard_allowlist = DashboardTableAllowlist(dbt_helper=dbt_helper)
        self.sql_guard = SqlGuard(dashboard_allowlist=self.dashboard_allowlist)
        self.relevance_detector = DashboardRelevanceDetector()
        self.capabilities_prompt = (
            "You are a helpful assistant for program data questions. "
            "Briefly explain what you can do: retrieve dashboard/chart/dbt context, "
            "run safe read-only SQL for counts/trends/breakdowns, and clarify metrics. "
            "Keep answers concise, friendly, and non-technical when possible."
        )
        
        # Initialize multi-context system
        try:
            self.multi_context_loader = MultiContextLoader(ngo_context_folder)
            # Load initial context (org-only until dashboard is selected)
            self.human_context = self.multi_context_loader.get_context_for_dashboard(None)
            self.current_context = self.human_context
            logger.info("Multi-context system initialized successfully")
        except Exception as e:
            logger.warning(f"Could not load multi-context system from {ngo_context_folder}: {e}")
            self.human_context = "Context file missing."
            self.current_context = self.human_context
        
        # Tool registry for OpenAI function calling
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "retrieve_docs",
                    "description": "Search for relevant charts, datasets, dbt models, or context sections.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "types": {
                                "type": "array",
                                "items": {"type": "string", "enum": ["chart", "dataset", "context", "dbt_model"]},
                                "description": "Document types to search"
                            },
                            "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function", 
                "function": {
                    "name": "get_schema_snippets",
                    "description": "Get column information for database tables.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tables": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Fully-qualified table names (schema.table)"
                            }
                        },
                        "required": ["tables"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_dbt_models",
                    "description": "Search dbt models by keyword to find relevant data models.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query for model names/descriptions"},
                            "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_dbt_model_info",
                    "description": "Get detailed information about a specific dbt model.",
                    "parameters": {
                        "type": "object", 
                        "properties": {
                            "model_name": {"type": "string", "description": "Model name or schema.table"}
                        },
                        "required": ["model_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_distinct_values",
                    "description": "Get distinct values for a column (required before filtering on text columns).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "table": {"type": "string", "description": "Fully-qualified table name"},
                            "column": {"type": "string", "description": "Column name"},
                            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}
                        },
                        "required": ["table", "column"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_sql_query",
                    "description": "Execute a read-only SQL query on the database.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string", "description": "SELECT query to execute"}
                        },
                        "required": ["sql"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_tables_by_keyword",
                    "description": "Find tables whose name or columns match a keyword (no hard-coding).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "keyword": {"type": "string", "description": "Keyword such as donor, funding, student"},
                            "limit": {"type": "integer", "default": 15, "minimum": 1, "maximum": 50}
                        },
                        "required": ["keyword"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "check_table_row_count",
                    "description": "Get the total number of rows in a table to check if it has data.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "table": {"type": "string", "description": "Fully-qualified table name (schema.table)"}
                        },
                        "required": ["table"]
                    }
                }
            }
        ]
        
        # Different LLM configurations for different scenarios
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.0,
            api_key=config.openai_api_key,
        )

        # Track distinct calls to avoid re-fetching and to gate SQL execution
        self._distinct_cache: set[tuple[str, str]] = set()
        self._openai_client = OpenAI(api_key=config.openai_api_key)
        
        # Auto/required bindings (kept for legacy small-talk path)
        self.llm_with_tools_auto = self.llm.bind_tools(self.tools, tool_choice="auto")
        self.llm_with_tools_required = self.llm.bind_tools(self.tools, tool_choice="required")

        # Build LangGraph to drive the flow
        self.graph = self._build_langgraph()

    # ---------- LangGraph setup ----------

    class _State(TypedDict, total=False):
        user_query: str
        conversation_history: List[Dict[str, str]]
        selected_dashboard_id: Optional[str]
        allow_retrieval: bool
        conv_context: ConversationContext
        intent_response: Any
        agent_response: AgentResponse

    def _build_langgraph(self):
        g = StateGraph(self._State)

        g.add_node("init_context", self._node_init_context)
        g.add_node("route_intent", self._node_route_intent)
        g.add_node("simple_intent", self._node_simple_intent)
        g.add_node("follow_up", self._node_follow_up)
        g.add_node("new_query", self._node_new_query)

        g.add_edge(START, "init_context")
        g.add_edge("init_context", "route_intent")

        def _route_after_intent(state: "EnhancedToolOrchestrator._State") -> str:
            intent = state["intent_response"].intent
            if intent in ["small_talk", "irrelevant", "needs_clarification"]:
                return "simple_intent"
            if intent in ["follow_up_sql", "follow_up_context"]:
                return "follow_up"
            return "new_query"

        g.add_conditional_edges("route_intent", _route_after_intent, {
            "simple_intent": "simple_intent",
            "follow_up": "follow_up",
            "new_query": "new_query",
        })

        g.add_edge("simple_intent", END)
        g.add_edge("follow_up", END)
        g.add_edge("new_query", END)

        return g.compile()

    # ---------- LangGraph nodes ----------

    def _node_init_context(self, state: _State) -> _State:
        """Align allowlist/context based on selected dashboard."""
        selected_dashboard_id = state.get("selected_dashboard_id")
        self.selected_dashboard_id = selected_dashboard_id
        self._update_dashboard_allowlist(selected_dashboard_id)
        self._update_dashboard_context(selected_dashboard_id)
        self._update_relevance_detector_context()
        return state

    def _node_route_intent(self, state: _State) -> _State:
        conv_context = self.conversation_manager.extract_conversation_context(state.get("conversation_history") or [])
        intent_response = self.router.classify_intent(state["user_query"], state.get("conversation_history"))
        state["conv_context"] = conv_context
        state["intent_response"] = intent_response
        return state

    def _node_simple_intent(self, state: _State) -> _State:
        intent_response = state["intent_response"]
        state["agent_response"] = self._handle_simple_intent(intent_response, state["user_query"])
        return state

    def _node_follow_up(self, state: _State) -> _State:
        intent_response = state["intent_response"]
        conv_context = state["conv_context"]
        state["agent_response"] = self._handle_follow_up_query(
            state["user_query"],
            intent_response,
            conv_context,
            state.get("allow_retrieval", True),
        )
        return state

    def _node_new_query(self, state: _State) -> _State:
        intent_response = state["intent_response"]
        state["agent_response"] = self._handle_new_query(
            state["user_query"],
            intent_response,
            state.get("allow_retrieval", True),
        )
        return state
    
    def process_query(
        self,
        user_query: str,
        allow_retrieval: bool = True,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        selected_dashboard_id: Optional[str] = None,
    ) -> AgentResponse:
        """Process user query via LangGraph (functionality preserved)."""
        initial_state: EnhancedToolOrchestrator._State = {
            "user_query": user_query,
            "allow_retrieval": allow_retrieval,
            "conversation_history": conversation_history or [],
            "selected_dashboard_id": selected_dashboard_id,
        }
        final_state = self.graph.invoke(initial_state)
        return final_state["agent_response"]
    
    def _handle_simple_intent(self, intent_response, user_query: str) -> AgentResponse:
        """Handle intents that don't require tools"""
        
        if intent_response.intent == "small_talk":
            response_text = self._generate_small_talk_response(user_query)
        elif intent_response.intent == "irrelevant":
            response_text = "I can help with questions about program data, metrics, and dashboard explanations. Please ask about your organization's programs or data."
        else:  # needs_clarification
            response_text = "Could you be more specific? For example, which metric or program are you asking about, and for what time period?"
            
        return AgentResponse(
            response_text=response_text,
            sources_used=[],
            chart_ids_used=[],
            dataset_ids_used=[],
            execution_info={
                "intent": intent_response.intent,
                "routing_method": "simple_intent"
            }
        )
    
    def _handle_follow_up_query(self, user_query: str, intent_response, conv_context: ConversationContext, allow_retrieval: bool) -> AgentResponse:
        """Handle follow-up queries with context reuse"""
        
        # Retrieval is always enabled now
        pass
        
        # Build messages with follow-up context
        follow_up_prompt = self.conversation_manager.build_follow_up_context_prompt(conv_context, user_query)
        modification_type = self.conversation_manager.detect_sql_modification_type(user_query)
        
        messages = [
            {"role": "system", "content": self._build_follow_up_system_prompt()},
            {"role": "system", "content": follow_up_prompt},
            {"role": "system", "content": f"MODIFICATION_TYPE: {modification_type}"},
            {"role": "user", "content": user_query},
        ]

        return self._execute_tool_loop(messages, intent_response, max_turns=6, user_query=user_query)
    
    def _handle_new_query(self, user_query: str, intent_response, allow_retrieval: bool) -> AgentResponse:
        """Handle new queries (not follow-ups)"""
        
        # Retrieval is always enabled now
        pass
        
        # Build messages for new query (raw OpenAI format for reliability)
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": user_query},
        ]
        
        return self._execute_tool_loop(messages, intent_response, max_turns=15, user_query=user_query)

    def _execute_tool_loop(self, messages: List[Dict[str, Any]], intent_response, max_turns: int, user_query: str = "") -> AgentResponse:
        """Execute tool loop using raw OpenAI chat completions."""
        tool_trace = []
        retrieved_ids = []
        last_sql = None
        last_sql_result = None

        for turn in range(max_turns):
            tool_choice = "required" if intent_response.force_tool_usage and turn == 0 else "auto"
            ai_msg = self._openai_chat(messages, tool_choice)

            tool_calls = ai_msg.get("tool_calls", [])
            assistant_record = {"role": "assistant", "content": ai_msg.get("content", "")}
            if tool_calls:
                assistant_record["tool_calls"] = [
                    {
                        "id": call.get("id"),
                        "type": "function",
                        "function": {
                            "name": call.get("name"),
                            "arguments": call.get("args") if isinstance(call.get("args"), str) else json.dumps(call.get("args", {}))
                        },
                    }
                    for call in tool_calls
                ]
            messages.append(assistant_record)

            if not tool_calls:
                return AgentResponse(
                    response_text=ai_msg.get("content", ""),
                    sql_used=last_sql,
                    sources_used=retrieved_ids,
                    chart_ids_used=[],
                    dataset_ids_used=[],
                    execution_info={
                        "intent": intent_response.intent,
                        "tool_calls": tool_trace,
                        "turns": turn + 1,
                        "sql_result": last_sql_result
                    }
                )

            for call in tool_calls:
                call_id = call.get("id")
                name = call.get("name")
                args = call.get("args") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}

                result = self._execute_tool(name, args)
                tool_trace.append({"tool": name, "args": args, "result": result})

                if name == "retrieve_docs":
                    retrieved_ids.extend([doc.get("doc_id", "") for doc in result.get("docs", [])])
                elif name == "run_sql_query":
                    if result.get("error") != "must_fetch_distinct_values":
                        last_sql = result.get("sql_used")
                        last_sql_result = {
                            "success": result.get("success"),
                            "row_count": result.get("row_count"),
                            "data_preview": result.get("data_preview"),
                            "columns": result.get("columns"),
                            "rows": result.get("rows"),
                            "error": result.get("error"),
                        }
                        if result.get("success"):
                            # Return immediately with the successful SQL result
                            return AgentResponse(
                                response_text=result.get("data_preview") or "Query executed successfully.",
                                sql_used=last_sql,
                                sources_used=retrieved_ids,
                                chart_ids_used=[],
                                dataset_ids_used=[],
                                execution_info={
                                    "intent": intent_response.intent,
                                    "tool_calls": tool_trace,
                                    "turns": turn + 1,
                                    "sql_result": last_sql_result
                                }
                            )

                messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, default=str)})

        # Max turns hit: if we have a successful SQL result, use it; otherwise apologize
        if last_sql_result and last_sql_result.get("success"):
            return AgentResponse(
                response_text=last_sql_result.get("data_preview") or "Query executed successfully.",
                sql_used=last_sql,
                sources_used=retrieved_ids,
                chart_ids_used=[],
                dataset_ids_used=[],
                execution_info={
                    "intent": intent_response.intent,
                    "tool_calls": tool_trace,
                    "turns": max_turns,
                    "max_turns_reached": True,
                    "sql_result": last_sql_result
                }
            )

        # Analyze why no results were found and provide intelligent error message
        no_results_context = {
            "tables_found": len([call for call in tool_trace if call.get('tool') == 'list_tables_by_keyword']),
            "vector_results": len([call for call in tool_trace if call.get('tool') == 'retrieve_docs']),
            "tool_calls": len(tool_trace),
            "sql_attempts": len([call for call in tool_trace if call.get('tool') == 'run_sql_query']),
            "max_turns_reached": True
        }
        
        # Use the passed user query for intelligent error messaging
        intelligent_error_result = self._handle_no_results_intelligently(user_query, no_results_context)

        return AgentResponse(
            response_text=intelligent_error_result["error_message"],
            sql_used=last_sql,
            sources_used=retrieved_ids,
            chart_ids_used=[],
            dataset_ids_used=[],
            execution_info={
                "intent": intent_response.intent,
                "tool_calls": tool_trace,
                "turns": max_turns,
                "max_turns_reached": True,
                "sql_result": last_sql_result,
                "no_results_context": no_results_context,
                "intelligent_error": intelligent_error_result
            }
        )

    def _openai_chat(self, messages: List[Dict[str, Any]], tool_choice: str) -> Dict[str, Any]:
        import time
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self._openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    tools=self.tools,
                    tool_choice=tool_choice,
                    temperature=0.0,
                )
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"OpenAI API call failed after {max_retries} attempts: {e}")
                    return {"content": "I'm experiencing technical difficulties. Please try again.", "tool_calls": []}
                time.sleep(2 ** attempt)  # exponential backoff
        msg = response.choices[0].message
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": tc.function.arguments,
                })
        return {"content": msg.content or "", "tool_calls": tool_calls}

    def _extract_tool_calls(self, ai_msg: AIMessage) -> List[Dict[str, Any]]:
        """Extract and normalize tool calls from an LLM response (kept for fallback/legacy)."""
        tool_calls = []
        raw_calls = []
        if hasattr(ai_msg, 'tool_calls') and ai_msg.tool_calls:
            raw_calls.extend(ai_msg.tool_calls)
        extra = getattr(ai_msg, 'additional_kwargs', {}) or {}
        if extra.get('tool_calls'):
            raw_calls.extend(extra['tool_calls'])

        for call in raw_calls:
            # Dict formats (OpenAI response)
            if isinstance(call, dict):
                call_id = call.get("id")
                if not call_id:
                    logger.warning("Skipping tool call without id (dict)")
                    continue
                fn = call.get("function") or {}
                name = call.get("name") or fn.get("name")
                args = call.get("args") or fn.get("arguments") or {}
                tool_calls.append({"id": call_id, "name": name, "args": args})
                continue

            # LangChain ToolCall objects
            call_id = getattr(call, 'id', None)
            if not call_id:
                logger.warning("Skipping tool call without id (object)")
                continue
            fn = getattr(call, 'function', None)
            if fn is not None:
                tool_calls.append({"id": call_id, "name": getattr(fn, 'name', None), "args": getattr(fn, 'arguments', {})})
            else:
                tool_calls.append({"id": call_id, "name": getattr(call, 'name', None), "args": getattr(call, 'args', {})})

        return tool_calls
    
    def _execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute individual tool and return result"""
        try:
            if name == "run_sql_query":
                return self._run_sql_with_distinct_guard(args)
            if name == "retrieve_docs":
                return self._tool_retrieve_docs(args)
            elif name == "get_schema_snippets":
                return self._tool_get_schema_snippets(args)
            elif name == "search_dbt_models":
                return self._tool_search_dbt_models(args)
            elif name == "get_dbt_model_info":
                return self._tool_get_dbt_model_info(args)
            elif name == "get_distinct_values":
                res = self._tool_get_distinct_values(args)
                if not res.get("error"):
                    tbl, col = res.get("table"), res.get("column")
                    if tbl and col:
                        self._distinct_cache.add((tbl.lower(), col.lower()))
                return res
            elif name == "list_tables_by_keyword":
                return self._tool_list_tables_by_keyword(args)
            elif name == "check_table_row_count":
                return self._tool_check_table_row_count(args)
            else:
                return {"error": f"Unknown tool: {name}"}
                
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return {"error": str(e)}
    
    def _tool_retrieve_docs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve relevant documents from vector store"""
        query = args.get("query", "")
        types = args.get("types", ["chart", "dataset", "context", "dbt_model"])
        limit = args.get("limit", 8)
        
        docs = []
        for doc_type in types:
            # Build filter metadata for ChromaDB
            if doc_type == "chart" and hasattr(self, 'selected_dashboard_id') and self.selected_dashboard_id:
                # Use ChromaDB $and operator for multiple conditions
                filter_meta = {
                    "$and": [
                        {"type": {"$eq": doc_type}},
                        {"dashboard_id": {"$eq": self.selected_dashboard_id}}
                    ]
                }
            else:
                # Single condition filter
                filter_meta = {"type": {"$eq": doc_type}}
            
            results = self.vectorstore.retrieve(
                query, 
                n_results=limit, 
                filter_metadata=filter_meta
            )
            logger.info(f"Retrieved {len(results)} {doc_type} docs with filter {filter_meta}")
            
            # Apply allowlist filtering for dbt_model documents
            if doc_type == "dbt_model" and hasattr(self, 'dashboard_allowlist'):
                filtered_results = []
                for result in results:
                    # Extract table name from dbt model metadata
                    metadata = result.get("metadata", {})
                    dbt_model = metadata.get("dbt_model", "")
                    schema = metadata.get("schema", "")
                    
                    if schema and dbt_model:
                        table_name = f"{schema}.{dbt_model}"
                        if self.dashboard_allowlist.is_allowed(table_name):
                            filtered_results.append(result)
                        else:
                            logger.debug(f"DBT model {table_name} filtered out by dashboard allowlist")
                    else:
                        # Include if no clear table mapping
                        filtered_results.append(result)
                
                logger.info(f"Dashboard allowlist filtered {len(results)} -> {len(filtered_results)} dbt_model docs")
                docs.extend(filtered_results)
            else:
                docs.extend(results)

        # If returned docs types don't overlap requested types (or nothing found), retry once with all types
        returned_types = { (d.get("metadata") or {}).get("type") for d in docs }
        if (not docs) or (set(types) and returned_types and not (returned_types & set(types))):
            docs = []
            for doc_type in ["chart", "dataset", "context", "dbt_model"]:
                # Build filter metadata for retry with ChromaDB syntax
                if doc_type == "chart" and hasattr(self, 'selected_dashboard_id') and self.selected_dashboard_id:
                    # Use ChromaDB $and operator for multiple conditions
                    filter_meta = {
                        "$and": [
                            {"type": {"$eq": doc_type}},
                            {"dashboard_id": {"$eq": self.selected_dashboard_id}}
                        ]
                    }
                else:
                    # Single condition filter
                    filter_meta = {"type": {"$eq": doc_type}}
                
                results = self.vectorstore.retrieve(
                    query,
                    n_results=limit,
                    filter_metadata=filter_meta
                )
                
                # Apply allowlist filtering for dbt_model documents in retry as well
                if doc_type == "dbt_model" and hasattr(self, 'dashboard_allowlist'):
                    filtered_results = []
                    for result in results:
                        # Extract table name from dbt model metadata
                        metadata = result.get("metadata", {})
                        dbt_model = metadata.get("dbt_model", "")
                        schema = metadata.get("schema", "")
                        
                        if schema and dbt_model:
                            table_name = f"{schema}.{dbt_model}"
                            if self.dashboard_allowlist.is_allowed(table_name):
                                filtered_results.append(result)
                            else:
                                logger.debug(f"DBT model {table_name} filtered out by dashboard allowlist (retry)")
                        else:
                            # Include if no clear table mapping
                            filtered_results.append(result)
                    
                    docs.extend(filtered_results)
                else:
                    docs.extend(results)

        # Auto-enrich with dbt model hits for the same query (gives LLM real tables)
        # Filter by dashboard allowlist
        dbt_models = []
        if self.dbt_helper:
            try:
                all_models = self.dbt_helper.find_models(query)
                # Filter models by allowlist
                for model in all_models:
                    table_name = f"{model.schema}.{model.name}"
                    if self.dashboard_allowlist.is_allowed(table_name):
                        dbt_models.append(model)
                    else:
                        logger.debug(f"DBT model {table_name} filtered out by dashboard allowlist in retrieve_docs")
                # Apply limit after filtering
                dbt_models = dbt_models[:limit]
            except Exception:
                dbt_models = []
        for m in dbt_models:
            docs.append({
                "content": m.description or m.name,
                "metadata": {
                    "type": "dbt_model",
                    "dbt_model": m.name,
                    "schema": m.schema,
                    "database": m.database,
                    "columns": [c.name for c in (m.columns or [])][:40]
                },
                "doc_id": f"dbt_model_{m.schema}.{m.name}",
                "similarity_score": 1.0,
                "rank": 0
            })

        # Post-process vector store results to filter dbt_model documents by allowlist
        filtered_docs = []
        filtered_count = 0
        
        for doc in docs:
            doc_type = doc.get("metadata", {}).get("type")
            if doc_type == "dbt_model":
                # Check if this dbt model is allowed
                schema = doc.get("metadata", {}).get("schema", "")
                model_name = doc.get("metadata", {}).get("dbt_model", "")
                table_name = f"{schema}.{model_name}" if schema and model_name else model_name
                
                if self.dashboard_allowlist.is_allowed(table_name):
                    filtered_docs.append(doc)
                else:
                    filtered_count += 1
                    logger.debug(f"Vector store dbt_model {table_name} filtered out by dashboard allowlist")
            else:
                # Non-dbt documents pass through (charts already filtered by dashboard_id)
                filtered_docs.append(doc)
        
        logger.info(f"Retrieved {len(filtered_docs)} docs after allowlist filtering ({filtered_count} dbt models filtered)")
        return {"docs": filtered_docs, "count": len(filtered_docs)}
    
    def _tool_get_schema_snippets(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get table column information"""
        tables = args.get("tables", [])
        
        # Filter tables by allowlist
        allowed_tables = []
        filtered_tables = []
        
        for table in tables:
            if self.dashboard_allowlist.is_allowed(table):
                allowed_tables.append(table)
            else:
                filtered_tables.append(table)
                logger.debug(f"Table {table} filtered out by dashboard allowlist")
        
        if filtered_tables:
            logger.info(f"Filtered {len(filtered_tables)} tables by dashboard allowlist: {filtered_tables}")
        
        # Prefer prod schemas when duplicates exist
        preferred: Dict[str, Dict[str, Any]] = {}
        for table in allowed_tables:
            # Auto-upgrade to prod schema if available
            base = table.split(".", 1)[1] if "." in table else table
            prod_candidate = f"prod.{base}"
            if not table.startswith("prod.") and self.schema_index.table_exists(prod_candidate):
                table = prod_candidate

            columns = self.schema_index.get_table_columns(table)
            # Fallback to dbt manifest if DB schema is empty
            if (not columns) and self.dbt_helper:
                model = None
                if "." in table:
                    schema, tbl = table.split(".", 1)
                    model = self.dbt_helper.get_model_by_table(schema, tbl)
                    # Try dev_prod if prod not found in manifest
                    if model is None and schema == "prod":
                        model = self.dbt_helper.get_model_by_table("dev_prod", tbl)
                    if model is None and schema == "prod":
                        model = self.dbt_helper.get_model_by_table("dev_intermediate", tbl)
                else:
                    model = self.dbt_helper.models.get(table)
                if model and model.columns:
                    columns = [{"name": c.name, "type": c.type, "nullable": True} for c in model.columns]

            if not columns:
                continue
            rank = 0
            schema = table.split(".", 1)[0] if "." in table else ""
            if schema.lower().startswith("prod"):
                rank = -1  # best
            elif "prod" in schema.lower():
                rank = 0
            else:
                rank = 1
            existing = preferred.get(base)
            if existing is None or rank < existing["rank"]:
                preferred[base] = {"table": table, "columns": columns, "rank": rank}

        snippets = [{"table": v["table"], "columns": v["columns"]} for v in preferred.values()]
        # Order richer schemas first to guide the LLM toward fuller tables
        snippets.sort(key=lambda s: len(s.get("columns", [])), reverse=True)
        
        result = {"tables": snippets}
        
        # Add information about filtered tables
        if filtered_tables:
            result["filtered_tables"] = filtered_tables
            result["filter_note"] = f"{len(filtered_tables)} tables were filtered out because they are not used by the current dashboard"

        return result

    def _tool_list_tables_by_keyword(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Return tables whose name or columns contain the keyword (case-insensitive)."""
        keyword = (args.get("keyword") or "").lower().strip()
        limit = int(args.get("limit", 15))
        if not keyword:
            return {"tables": []}
        
        matches = []
        clean_matches = []  # Prioritize clean schemas
        
        for tbl in self.schema_index.list_tables():
            # Include production-ready schemas
            schema = tbl.split('.')[0].lower()
            allowed_schemas = ['prod', 'staging', 'intermediate', 'dev_prod', 'dev_intermediate']
            if schema not in allowed_schemas:
                continue
            
            # Check dashboard allowlist
            if not self.dashboard_allowlist.is_allowed(tbl):
                logger.debug(f"Table {tbl} filtered out by dashboard allowlist")
                continue
                
            cols = self.schema_index.get_table_columns(tbl)
            col_names = [c.get("name", "") for c in cols]
            if keyword in tbl.lower() or any(keyword in c.lower() for c in col_names):
                table_info = {"table": tbl, "columns": col_names[:40]}
                clean_matches.append(table_info)
                    
            if len(clean_matches) + len(matches) >= limit:
                break
        
        # Return clean tables first, then others, with hint about available columns
        all_tables = (clean_matches + matches)[:limit]
        if all_tables:
            return {
                "tables": all_tables,
                "hint": f"Found {len(all_tables)} tables (filtered by current dashboard). Check columns with get_schema_snippets before assuming table structure."
            }
        
        # If no tables found, provide helpful message about dashboard filtering
        allowlist_summary = self.dashboard_allowlist.get_summary()
        if allowlist_summary["total_allowed"] > 0:
            return {
                "tables": [], 
                "hint": f"No tables matching '{keyword}' found in current dashboard scope. Dashboard allows {allowlist_summary['total_allowed']} tables. Try broader keywords or check if the table is used by the current dashboard."
            }
        else:
            return {"tables": [], "hint": "No tables found. Try broader keywords."}
    
    def _tool_check_table_row_count(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Check if a table has data by counting rows"""
        table = args.get("table", "")
        if not table:
            return {"error": "Table name required"}
        
        # Check allowlist
        if not self.dashboard_allowlist.is_allowed(table):
            return {
                "error": "table_not_allowed", 
                "table": table,
                "message": f"Table {table} is not accessible in the current dashboard context. Use list_tables_by_keyword to find available tables."
            }
        
        try:
            sql = f"SELECT COUNT(*) as row_count FROM {table} LIMIT 1"
            result = self.postgres.execute_sql(sql)
            if result["success"] and result.get("dataframe") is not None:
                df = result["dataframe"]
                if not df.empty:
                    row_count = df.iloc[0]["row_count"]
                    return {"table": table, "row_count": int(row_count), "has_data": row_count > 0}
            return {"table": table, "row_count": 0, "has_data": False, "error": "Could not count rows"}
        except Exception as e:
            logger.error(f"Row count check failed for {table}: {e}")
            return {"table": table, "error": str(e), "has_data": False}
    
    def _tool_search_dbt_models(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search dbt models by keyword"""
        if not self.dbt_helper:
            return {"error": "DBT helper not available"}
            
        query = args.get("query", "")
        limit = args.get("limit", 8)
        
        # Search all models, not just prod_gender
        models = self.dbt_helper.find_models(query)
        
        # Filter models by allowlist
        allowed_models = []
        for model in models:
            table_name = f"{model.schema}.{model.name}"
            if self.dashboard_allowlist.is_allowed(table_name):
                allowed_models.append(model)
            else:
                logger.debug(f"DBT model {table_name} filtered out by dashboard allowlist")
        
        # Apply limit after filtering
        allowed_models = allowed_models[:limit]
        
        results = []
        for model in allowed_models:
            results.append({
                "name": model.name,
                "schema": model.schema,
                "database": model.database,
                "description": model.description,
                "columns": [c.name for c in (model.columns or [])][:20]
            })
            
        return {
            "models": results, 
            "count": len(results),
            "note": f"Results filtered by current dashboard scope. {len(results)} of {len(models)} models shown."
        }
    
    def _tool_get_dbt_model_info(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed dbt model information"""
        if not self.dbt_helper:
            return {"error": "DBT helper not available"}
            
        model_name = args.get("model_name", "")
        
        # Handle schema.table format
        if "." in model_name:
            schema, table = model_name.split(".", 1)
            model = self.dbt_helper.get_model_by_table(schema, table)
        else:
            model = self.dbt_helper.models.get(model_name)
            
        if not model:
            return {"error": f"Model not found: {model_name}"}
        
        columns = []
        for col in (model.columns or [])[:50]:
            columns.append({
                "name": col.name,
                "type": col.type,
                "description": col.description
            })
        
        lineage = self.dbt_helper.get_lineage(model.name)
        
        return {
            "model": model.name,
            "schema": model.schema,
            "database": model.database, 
            "description": model.description,
            "columns": columns,
            "upstream": lineage.get("upstream", []),
            "downstream": lineage.get("downstream", [])
        }
    
    def _tool_get_distinct_values(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get distinct values for a column"""
        table = args.get("table", "")
        column = args.get("column", "")
        limit = args.get("limit", 50)
        
        # Check allowlist
        if not self.dashboard_allowlist.is_allowed(table):
            return {
                "error": "table_not_allowed", 
                "table": table,
                "message": f"Table {table} is not accessible in the current dashboard context. Use list_tables_by_keyword to find available tables."
            }
        
        try:
            values = self.postgres.get_distinct_values(table, column, limit)
            return {
                "table": table,
                "column": column,  
                "values": values,
                "count": len(values)
            }
        except Exception as e:
            logger.error(f"get_distinct_values failed for {table}.{column}: {e}")
            return {"error": str(e), "table": table, "column": column}
    
    def _tool_run_sql_query(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute SQL query with safety checks"""
        sql = args.get("sql", "")

        # Validate SQL safety
        validation = self.sql_guard.validate_sql(sql)
        if not validation.is_valid:
            return {"error": "sql_validation_failed", "issues": validation.errors}

        # Execute SQL
        final_sql = validation.corrected_sql or sql
        exec_result = self.postgres.execute_sql(final_sql)

        # Format result
        preview = None
        if exec_result["success"] and exec_result.get("dataframe") is not None:
            df = exec_result["dataframe"]
            if not df.empty:
                preview = df.to_string(index=False)

        return {
            "success": exec_result["success"],
            "row_count": exec_result.get("row_count"),
            "data_preview": preview,
            "error": exec_result.get("error"),
            "sql_used": final_sql,
            "columns": exec_result.get("columns"),
            "rows": exec_result.get("rows"),
        }

    def _run_sql_with_distinct_guard(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure distinct values were fetched for string filters; if missing, signal the LLM to fetch then retry."""
        sql = args.get("sql", "") or ""

        # Check allowlist validation first
        allowlist_validation = self._validate_sql_allowlist(sql)
        if not allowlist_validation["valid"]:
            return {
                "error": "table_not_allowed",
                "invalid_tables": allowlist_validation["invalid_tables"],
                "message": allowlist_validation["message"]
            }

        # If referenced table does not exist, suggest using list_tables_by_keyword to find it
        import re
        table_match = re.search(r"FROM\s+([`\"]?)([\w\.]+)\1", sql, re.IGNORECASE)
        if table_match:
            candidate_table = table_match.group(2)
            if not self.schema_index.table_exists(candidate_table):
                return {
                    "error": "table_not_found",
                    "missing_table": candidate_table,
                    "message": f"Table {candidate_table} does not exist. You must call list_tables_by_keyword first to discover available tables, then use the EXACT table name returned. Do not modify or assume schema names."
                }

        # Attempt to rewrite SQL to a table that actually contains referenced columns
        sql = self._rewrite_sql_for_missing_columns(sql)

        args = dict(args)
        args["sql"] = sql
        missing = self._missing_distinct(sql)
        if missing:
            return {
                "error": "must_fetch_distinct_values",
                "missing": missing,
                "message": "Call get_distinct_values for these columns, then regenerate the SQL using one of the returned values."
            }
        return self._tool_run_sql_query(args)
    
    def _handle_no_results_intelligently(self, user_query: str, no_results_context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate intelligent error message when no results are found"""
        try:
            relevance_result = self.relevance_detector.analyze_query_relevance(
                query=user_query,
                current_dashboard_id=self.selected_dashboard_id,
                no_results_context=no_results_context
            )
            
            logger.info(f"Relevance analysis: {relevance_result.failure_reason} (confidence: {relevance_result.confidence:.2f})")
            
            # Get dashboard suggestions if relevant
            dashboard_suggestions = []
            if relevance_result.failure_reason == "cross_dashboard_question":
                suggestions = self.relevance_detector.get_dashboard_suggestions(user_query)
                dashboard_suggestions = suggestions[:2]  # Top 2 suggestions
            
            return {
                "error_message": relevance_result.suggested_action,
                "failure_reason": relevance_result.failure_reason,
                "confidence": relevance_result.confidence,
                "dashboard_suggestions": dashboard_suggestions,
                "extracted_keywords": relevance_result.extracted_keywords
            }
            
        except Exception as e:
            logger.error(f"Error in relevance detection: {e}")
            # Fallback to generic message
            return {
                "error_message": "I couldn't find relevant data for your question. Please try rephrasing or check if you're viewing the correct dashboard.",
                "failure_reason": "unknown_error",
                "confidence": 0.0,
                "dashboard_suggestions": [],
                "extracted_keywords": []
            }
    
    def _validate_sql_allowlist(self, sql: str) -> Dict[str, Any]:
        """Validate that all tables in SQL are allowed by dashboard allowlist"""
        import re
        
        # Extract table references from SQL
        # Look for FROM and JOIN patterns
        table_patterns = [
            r"FROM\s+([`\"]?)([\w\.]+)\1",  # FROM table
            r"JOIN\s+([`\"]?)([\w\.]+)\1",  # JOIN table
            r"INTO\s+([`\"]?)([\w\.]+)\1",  # INSERT INTO (shouldn't happen but safety)
            r"UPDATE\s+([`\"]?)([\w\.]+)\1"  # UPDATE (shouldn't happen but safety)
        ]
        
        referenced_tables = set()
        for pattern in table_patterns:
            matches = re.finditer(pattern, sql, re.IGNORECASE)
            for match in matches:
                table_name = match.group(2)
                referenced_tables.add(table_name)
        
        # Check each table against allowlist
        invalid_tables = []
        for table in referenced_tables:
            if not self.dashboard_allowlist.is_allowed(table):
                invalid_tables.append(table)
        
        if invalid_tables:
            allowlist_summary = self.dashboard_allowlist.get_summary()
            message = (
                f"SQL references tables not available in current dashboard: {', '.join(invalid_tables)}. "
                f"Current dashboard allows {allowlist_summary['total_allowed']} tables. "
                f"Use list_tables_by_keyword to find available tables."
            )
            return {
                "valid": False,
                "invalid_tables": invalid_tables,
                "message": message
            }
        
        return {"valid": True, "invalid_tables": [], "message": ""}

    def _rewrite_sql_for_missing_columns(self, sql: str) -> str:
        """If referenced columns are missing in the chosen table, swap to a table that has them."""
        import re
        from copy import deepcopy

        table_match = re.search(r"FROM\\s+([\\w\\.]+)", sql, re.IGNORECASE)
        if not table_match:
            return sql
        table = table_match.group(1)
        columns_raw = self.schema_index.get_table_columns(table)
        columns_lower = {c["name"].lower() for c in columns_raw}

        # Extract columns from SELECT and GROUP BY
        col_tokens = set()
        select_match = re.search(r"SELECT\\s+(.*?)\\s+FROM", sql, re.IGNORECASE | re.DOTALL)
        if select_match:
            sel = select_match.group(1)
            col_tokens.update(re.findall(r'"([\\w\\s]+)"', sel))
            col_tokens.update(re.findall(r'\\b(\\w+)\\b', sel))
        group_match = re.search(r"GROUP\\s+BY\\s+(.*)", sql, re.IGNORECASE)
        if group_match:
            grp = group_match.group(1)
            col_tokens.update(re.findall(r'"([\\w\\s]+)"', grp))
            col_tokens.update(re.findall(r'\\b(\\w+)\\b', grp))

        missing_cols = [c for c in col_tokens if c and c.lower() not in columns_lower and c.upper() not in {"COUNT", "DISTINCT"}]
        if not missing_cols:
            return sql

        # Generic location fallback: if a requested location column is missing, try closest available (Chapter, District, School)
        location_aliases = [
            ("city", ["chapter", "district", "school", "region"]),
            ("chapter", ["district", "city", "school", "region"]),
        ]
        for missing in list(missing_cols):
            for target, alternatives in location_aliases:
                if missing.lower() == target:
                    for alt in alternatives:
                        candidate_table = self._find_table_with_columns([alt.title()], prefer_tables=None)
                        if candidate_table:
                            sql = sql.replace(table, candidate_table)
                            sql = re.sub(rf'\b{target}\b', f'"{alt.title()}"', sql, flags=re.IGNORECASE)
                            table = candidate_table
                            columns_raw = self.schema_index.get_table_columns(table)
                            columns_lower = {c["name"].lower() for c in columns_raw}
                            missing_cols = [c for c in col_tokens if c and c.lower() not in columns_lower and c.upper() not in {"COUNT", "DISTINCT"}]
                            break
                    break
            if not missing_cols:
                return sql

        # Find an alternative table that contains all missing columns
        candidate = self._find_table_with_columns(missing_cols)
        if candidate and candidate != table:
            sql = sql.replace(table, candidate)
        return sql

    def _find_table_with_columns(self, cols: list, prefer_tables: Optional[list] = None) -> str:
        """Return a table that contains all requested columns (no schema bias)."""
        tables = self.schema_index.list_tables()
        priority = []
        for t in tables:
            colnames = {c["name"].lower() for c in self.schema_index.get_table_columns(t)}
            if all(c.lower() in colnames for c in cols):
                priority.append(t)
        if not priority:
            return ""
        # If caller supplied preferred tables, pick the first that matches; otherwise return the first candidate.
        if prefer_tables:
            for p in prefer_tables:
                if p in priority:
                    return p
        return priority[0]
        return ""
    
    def _check_where_clauses_need_distinct_values(self, sql: str) -> Dict[str, Any]:
        """Check if SQL has WHERE clauses on text columns that need distinct value validation"""
        
        if not sql or "WHERE" not in sql.upper():
            return {"needs_distinct": False}
        
        # Simple check for text comparisons in WHERE
        # Look for patterns like: column = 'value' or column IN ('val1', 'val2')
        text_filter_patterns = [
            r"(\w+)\s*=\s*'([^']+)'",  # column = 'value'
            r"(\w+)\s+IN\s*\(\s*'([^']+)'",  # column IN ('value'...)
        ]
        
        for pattern in text_filter_patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                column = match.group(1)
                value = match.group(2)
                
                # Try to infer table from SQL
                table_match = re.search(r"FROM\s+([`\"]?)(\w+\.\w+)\1", sql, re.IGNORECASE)
                if table_match:
                    table = table_match.group(2)
                    return {
                        "needs_distinct": True,
                        "table": table,
                        "column": column,
                        "attempted_value": value
                    }
        
        return {"needs_distinct": False}

    def _missing_distinct(self, sql: str) -> List[Dict[str, str]]:
        """Return list of table/column pairs needing distinct values before SQL."""
        missing: List[Dict[str, str]] = []
        check = self._check_where_clauses_need_distinct_values(sql)
        if not check.get("needs_distinct"):
            return missing
        tbl = check.get("table")
        col = check.get("column")
        # If the column is not present in the target table, surface alternatives
        if tbl and col:
            table_cols = {c["name"].lower() for c in self.schema_index.get_table_columns(tbl)}
            if col.lower() not in table_cols:
                missing.append({
                    "table": tbl,
                    "column": col,
                    "error": "column_not_in_table",
                    "candidates": self._find_tables_with_column(col)
                })
                return missing
        if tbl and col and (tbl.lower(), col.lower()) not in self._distinct_cache:
            missing.append({"table": tbl, "column": col})
        return missing

    def _find_tables_with_column(self, column: str, limit: int = 10) -> List[str]:
        """Find tables in schema_index that contain the given column name (case-insensitive)."""
        matches = []
        col_lower = column.lower()
        for table in self.schema_index.list_tables():
            cols = self.schema_index.get_table_columns(table)
            if any(col_lower == c.get("name", "").lower() for c in cols):
                matches.append(table)
            if len(matches) >= limit:
                break
        return matches
    
    def _build_system_prompt(self) -> str:
        """Build system prompt for new queries"""
        return f"""You are a data analysis assistant with access to tools. Your job is to help users understand program data and answer their questions accurately.

IMPORTANT RULES:
1. For data questions: ALWAYS start by searching for relevant charts using retrieve_docs
2. Use chart metadata to identify which datasets/tables to query - charts are your roadmap to data
3. For definition questions: You may use tools to get context or answer from human context  
4. Never guess table names, column names, or data values
5. Always call get_distinct_values before using WHERE clauses on text columns
6. Only write SELECT queries, never INSERT/UPDATE/DELETE
7. CRITICAL: When list_tables_by_keyword returns tables, you MUST use the EXACT table names returned - never modify schema or table names
8. NEVER assume tables exist in specific schemas - always discover them using list_tables_by_keyword first
9. When counting entities (students, people, sites, states, programs, cases, etc.), avoid COUNT(*). Prefer COUNT(DISTINCT <identifier>) using the most specific ID/name field available (e.g., student_id, roll_no, state_name). If unsure which field uniquely identifies the entity, inspect schema first, and fetch distinct values for candidate ID columns before writing SQL.
9. When you propose SQL, immediately call run_sql_query to execute it. Do not ask for confirmation.
10. Call get_distinct_values only for columns you plan to filter in the current query.
11. Limit get_schema_snippets to the tables you intend to query (avoid extra tables).
12. If a requested geographic/location field is missing, choose the most specific available location dimension (e.g., city → chapter → school) and answer using that, explicitly noting the substitution in the response.
13. When someone asks for "changes" in metrics, look for increases and decreases by comparing values across time periods (baseline vs midline vs endline) or comparing current vs previous periods.
14. ONLY use these exact schemas: prod, dev_prod, staging, intermediate. NEVER use dev_staging, airbyte_internal, or any other dev_ prefixed schemas. Charts will guide you to the right tables.
15. IMPORTANT: Only tables relevant to the current dashboard are accessible. If a table is not found, it may not be relevant to this dashboard. Use charts from the current dashboard to guide your analysis.

Available tools:
- retrieve_docs: Find relevant charts, datasets, context, or dbt models
- search_dbt_models: Search for dbt models by keyword  
- get_dbt_model_info: Get detailed info about a specific dbt model
- get_schema_snippets: Get column names and types for tables
- get_distinct_values: Get actual values in a column (required before WHERE clauses)
- check_table_row_count: Check if a table has data before querying
- run_sql_query: Execute a read-only SQL query

Tool usage flow for data questions:
1. FIRST: Call retrieve_docs to find relevant CHARTS that match the question
2. If charts found: Use the dataset/table names from chart metadata to guide your queries
3. If no relevant chart datasets found: ALWAYS call list_tables_by_keyword with the main entity (e.g. "students", "fellowship", "baseline") 
4. Call get_schema_snippets ONLY for the exact table names returned by list_tables_by_keyword
5. Use the EXACT table names from step 3/4 in your SQL queries - do not change schema or table names
6. If filtering: Call get_distinct_values for filter columns
7. ALWAYS call run_sql_query with validated SQL - NEVER give up without trying

Human context about the organization:
{self.human_context}"""

    def _build_follow_up_system_prompt(self) -> str:
        """Build system prompt for follow-up queries"""
        return f"""You are handling a follow-up query that modifies a previous question.

FOLLOW-UP RULES:
1. Reuse context from the previous query when possible (tables, metrics, base SQL)
2. For SQL modifications: modify the previous SQL rather than starting from scratch
3. For new filters: ALWAYS call get_distinct_values first
4. For new dimensions: ensure the column exists in the schema
5. When you generate SQL, execute it by calling run_sql_query immediately; do not ask for confirmation.
6. Only fetch distinct values for columns you will filter, and limit schema lookups to tables you plan to query.

Human context:
{self.human_context}"""
    
    def _generate_small_talk_response(self, user_query: str) -> str:
        """Generate small talk via LLM using capabilities prompt."""
        prompt = (
            f"{self.capabilities_prompt}\n\n"
            f"User: {user_query}\n"
            "Answer briefly (<=60 tokens), warm tone, and mention you can pull real data if needed."
        )
        try:
            resp = self._openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": self.capabilities_prompt},
                          {"role": "user", "content": user_query}],
                max_tokens=80,
                temperature=0.5,
            )
            msg = resp.choices[0].message.content
            return msg.strip() if msg else "Hi! I can help with your program data and metrics. What would you like to know?"
        except Exception as e:
            logger.warning(f"Small talk generation failed, using fallback: {e}")
            return "Hi! I can help with your program data and metrics. What would you like to know?"
    
    def _update_dashboard_context(self, dashboard_id: Optional[str]):
        """Update the human context based on selected dashboard"""
        try:
            # Load context specific to the dashboard
            self.current_context = self.multi_context_loader.get_context_for_dashboard(dashboard_id)
            self.human_context = self.current_context
            
            if dashboard_id:
                logger.info(f"Updated context for dashboard: {dashboard_id}")
            else:
                logger.info("Updated to org-only context (no dashboard selected)")
                
        except Exception as e:
            logger.error(f"Error updating dashboard context: {e}")
            # Fallback to org context only
            try:
                contexts = self.multi_context_loader.load_all_contexts()
                self.human_context = contexts.org_context
            except Exception as fallback_error:
                logger.error(f"Fallback context loading failed: {fallback_error}")
                self.human_context = "Context loading failed."
    
    def _update_relevance_detector_context(self):
        """Update the relevance detector with current dashboard context"""
        try:
            if hasattr(self, 'relevance_detector') and self.relevance_detector:
                # Get all dashboard contexts for the relevance detector
                contexts = self.multi_context_loader.load_all_contexts()
                dashboard_contexts = {}
                for dashboard_id, context_content in contexts.dashboard_contexts.items():
                    dashboard_contexts[dashboard_id] = context_content
                
                # Update the relevance detector with all dashboard contexts
                if hasattr(self.relevance_detector, 'update_dashboard_contexts'):
                    self.relevance_detector.update_dashboard_contexts(dashboard_contexts)
                    logger.debug("Updated relevance detector with dashboard contexts")
        except Exception as e:
            logger.warning(f"Could not update relevance detector context: {e}")
    
    def _update_dashboard_allowlist(self, dashboard_id: Optional[str]):
        """Update the allowlist based on the selected dashboard"""
        if not dashboard_id or not self.dbt_helper:
            # No dashboard selected or no DBT helper available
            self.dashboard_allowlist = DashboardTableAllowlist(dbt_helper=self.dbt_helper)
            self.sql_guard = SqlGuard(dashboard_allowlist=self.dashboard_allowlist)
            logger.info("No dashboard allowlist restrictions - all tables accessible")
            return
        
        try:
            # Get dashboard charts from vectorstore metadata
            dashboard_charts = self._get_dashboard_charts(dashboard_id)
            if dashboard_charts:
                self.dashboard_allowlist.update_for_dashboard(dashboard_charts)
                summary = self.dashboard_allowlist.get_summary()
                logger.info(f"Updated dashboard allowlist for {dashboard_id}: {summary}")
            else:
                logger.warning(f"No charts found for dashboard {dashboard_id}")
                
        except Exception as e:
            logger.error(f"Failed to update dashboard allowlist: {e}")
            # Fallback to no restrictions
            self.dashboard_allowlist = DashboardTableAllowlist(dbt_helper=self.dbt_helper)
        
        # Update SQL guard with new allowlist
        self.sql_guard = SqlGuard(dashboard_allowlist=self.dashboard_allowlist)
    
    def _get_dashboard_charts(self, dashboard_id: str) -> List:
        """Get charts for a specific dashboard from vectorstore"""
        try:
            # Import here to avoid circular imports
            from retrieval.bhumi_parser import BhumiChart
            
            # Query vectorstore for charts belonging to this dashboard
            filter_meta = {
                "$and": [
                    {"type": {"$eq": "chart"}},
                    {"dashboard_id": {"$eq": dashboard_id}}
                ]
            }
            
            chart_docs = self.vectorstore.retrieve(
                query="dashboard charts", 
                n_results=50, 
                filter_metadata=filter_meta
            )
            
            # Convert retrieved docs back to BhumiChart objects
            charts = []
            for doc in chart_docs:
                metadata = doc.get('metadata', {})
                if 'data_source' in doc.get('content', ''):
                    # Extract chart info from content
                    content = doc.get('content', '')
                    lines = content.split('\n')
                    
                    # Parse chart details from content
                    chart_data = {
                        'chart_id': metadata.get('chart_id', ''),
                        'title': '',
                        'chart_type': '',
                        'chart_type_description': '',
                        'data_source': '',
                        'metric_calculation': '',
                        'filters': [],
                        'measures': [],
                        'dimensions': [],
                        'grain': ''
                    }
                    
                    for line in lines:
                        if line.startswith('Chart: '):
                            chart_data['title'] = line.replace('Chart: ', '')
                        elif line.startswith('Data Source: '):
                            chart_data['data_source'] = line.replace('Data Source: ', '')
                        elif line.startswith('Type: '):
                            type_info = line.replace('Type: ', '')
                            if '(' in type_info:
                                chart_data['chart_type'] = type_info.split('(')[0].strip()
                                chart_data['chart_type_description'] = type_info.split('(')[1].rstrip(')')
                        elif line.startswith('Metric Calculation: '):
                            chart_data['metric_calculation'] = line.replace('Metric Calculation: ', '')
                        elif line.startswith('Aggregation Level: '):
                            chart_data['grain'] = line.replace('Aggregation Level: ', '')
                    
                    # Create BhumiChart object
                    if chart_data['data_source']:  # Only include if we have a data source
                        chart = BhumiChart(**chart_data)
                        charts.append(chart)
            
            logger.info(f"Retrieved {len(charts)} charts for dashboard {dashboard_id}")
            return charts
            
        except Exception as e:
            logger.error(f"Error retrieving dashboard charts: {e}")
            return []
