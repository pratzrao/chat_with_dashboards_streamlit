import pandas as pd
from typing import Any, Dict, List, Optional
from agents.models import AgentResponse
from openai import OpenAI
from config import config


class FinalAnswerComposer:
    """Compose final user-facing answers from AgentResponse."""

    def __init__(self):
        self.client = OpenAI(api_key=config.openai_api_key)

    def compose(self, response: AgentResponse) -> Dict[str, Any]:
        sql_result = (response.execution_info or {}).get("sql_result") or {}
        rows = sql_result.get("rows") or []
        columns = sql_result.get("columns") or []
        tool_calls = (response.execution_info or {}).get("tool_calls") or []

        table_df: Optional[pd.DataFrame] = None
        if rows and columns:
            try:
                table_df = pd.DataFrame(rows, columns=columns)
            except Exception:
                table_df = None

        # Gather any retrieved documents (charts/datasets/dbt/context) to inform the answer
        retrieved_docs: List[str] = []
        for call in tool_calls:
            if call.get("tool") == "retrieve_docs":
                docs = call.get("result", {}).get("docs", []) or []
                for doc in docs[:8]:  # keep prompt compact
                    meta = doc.get("metadata", {}) or {}
                    name = meta.get("chart_id") or meta.get("dataset_id") or meta.get("dbt_model") or meta.get("title") or doc.get("doc_id")
                    ctype = meta.get("chart_type") or meta.get("type") or "doc"
                    snippet = (doc.get("content") or "")[:300]
                    retrieved_docs.append(f"[{ctype}] {name}: {snippet}")

        docs_text = "\n".join(retrieved_docs)

        # Delegate wording to LLM (brief, human)
        composed_text = response.response_text or ""
        try:
            prompt = (
                "You are crafting a clear, human-friendly answer for a dashboard user.\n"
                "Base answer (from tools or prior step):\n"
                f"{response.response_text or ''}\n\n"
                "Retrieved documents (charts/datasets/dbt/context) you can reference; include their names/types when relevant:\n"
                f"{docs_text}\n\n"
                "Execution context (do not expose SQL/tool jargon unless it helps clarity):\n"
                f"SQL: {response.sql_used or ''}\n"
                "If a table is provided, summarize the key number(s) succinctly, then mention the source table and grouping in plain language.\n"
                "If the user asked to list items (charts, models, columns, datasets, etc.), output all items you have from retrieved docs (up to the provided list) using concise bullets.\n"
                "Be concise but comprehensive when listing; otherwise keep answers under 2 sentences."
            )
            chat_resp = self.client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.2,
                max_tokens=800,
                messages=[
                    {"role": "system", "content": "You write concise, friendly data answers."},
                    {"role": "user", "content": prompt},
                ],
            )
            composed_text = chat_resp.choices[0].message.content.strip()
        except Exception:
            composed_text = response.response_text or ""

        return {
            "text": composed_text.strip(),
            "table": table_df,
        }
