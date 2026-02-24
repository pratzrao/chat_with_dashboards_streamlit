from typing import Dict, List, Any, Optional
from pydantic import BaseModel
from retrieval.vectorstore import VectorStore
from db.dbt_helpers import DbtHelper
from db.postgres import SchemaIndex

class ContextPack(BaseModel):
    dashboard_context: Dict[str, Any]
    retrieved: Dict[str, List[Dict[str, Any]]]
    schema_snippets: List[Dict[str, Any]]
    conversation_memory: Dict[str, Any]
    constraints: Dict[str, Any]

class ContextBuilder:
    def __init__(self, vectorstore: VectorStore, dbt_helper: DbtHelper, schema_index: SchemaIndex):
        self.vectorstore = vectorstore
        self.dbt_helper = dbt_helper
        self.schema_index = schema_index
    
    def build_context_pack(
        self,
        user_query: str,
        selected_dashboard_id: Optional[str] = None,
        conversation_history: List[Dict[str, str]] = None,
        last_sql_summary: Optional[str] = None
    ) -> ContextPack:
        """Build a context pack for the current user query"""
        
        # Retrieve relevant documents
        retrieved_charts = self.vectorstore.retrieve(
            user_query, 
            n_results=6, 
            filter_metadata={"type": "chart"}
        )
        
        retrieved_datasets = self.vectorstore.retrieve(
            user_query,
            n_results=4,
            filter_metadata={"type": "dataset"}
        )
        
        retrieved_context = self.vectorstore.retrieve(
            user_query,
            n_results=3,
            filter_metadata={"type": "context"}
        )
        
        # Build schema snippets for relevant tables
        relevant_tables = self._extract_relevant_tables(retrieved_charts, retrieved_datasets)
        schema_snippets = self._build_schema_snippets(relevant_tables)
        
        # Build conversation memory
        memory = {
            "last_turns": conversation_history[-3:] if conversation_history else [],
            "last_sql_summary": last_sql_summary
        }
        
        return ContextPack(
            dashboard_context={
                "selected_dashboard_id": selected_dashboard_id,
                "filters_applied": {}
            },
            retrieved={
                "charts": retrieved_charts,
                "datasets": retrieved_datasets,
                "context": retrieved_context
            },
            schema_snippets=schema_snippets,
            conversation_memory=memory,
            constraints={
                "sql_read_only": True,
                "default_limit": 500,
                "max_limit": 2000,
                "no_pii": True
            }
        )
    
    def _extract_relevant_tables(self, charts: List[Dict[str, Any]], 
                                 datasets: List[Dict[str, Any]]) -> List[str]:
        """Extract table names from retrieved charts and datasets"""
        tables = set()
        
        # From charts - look at dataset references
        for chart in charts:
            dataset_id = chart['metadata'].get('dataset_id', '')
            if dataset_id:
                # Try to map dataset to actual table
                for dataset in datasets:
                    if dataset['metadata'].get('dataset_id') == dataset_id:
                        schema = dataset['metadata'].get('schema', '')
                        table_name = dataset['metadata'].get('table_name', '')
                        if schema and table_name:
                            tables.add(f"{schema}.{table_name}")
        
        # From datasets directly
        for dataset in datasets:
            schema = dataset['metadata'].get('schema', '')
            table_name = dataset['metadata'].get('table_name', '')
            if schema and table_name:
                tables.add(f"{schema}.{table_name}")
        
        # Add common tables if none found
        if not tables:
            tables.update([
                "prod_gender.case_occurence",
                "prod_gender.champions",
                "prod_gender.counselling"
            ])
        
        return list(tables)
    
    def _build_schema_snippets(self, table_names: List[str]) -> List[Dict[str, Any]]:
        """Build schema snippets for relevant tables"""
        snippets = []
        
        for table_name in table_names:
            columns = self.schema_index.get_table_columns(table_name)
            if columns:
                # Filter out potential PII columns
                safe_columns = self._filter_pii_columns(columns)
                
                snippet = {
                    "table": table_name,
                    "columns": safe_columns
                }
                snippets.append(snippet)
        
        return snippets
    
    def _filter_pii_columns(self, columns: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Filter out columns that might contain PII"""
        pii_keywords = [
            'name', 'phone', 'email', 'address', 'national_id', 
            'id_number', 'contact', 'personal', 'identification',
            'mobile', 'telephone', 'firstname', 'lastname',
            'full_name', 'participant_name', 'survivor_name'
        ]
        
        safe_columns = []
        for col in columns:
            col_name_lower = col['name'].lower()
            is_pii = any(keyword in col_name_lower for keyword in pii_keywords)
            
            if is_pii:
                # Mark as PII but include for reference
                safe_col = col.copy()
                safe_col['is_pii'] = True
                safe_col['description'] = f"[PII] {safe_col.get('description', '')}"
                safe_columns.append(safe_col)
            else:
                safe_columns.append(col)
        
        return safe_columns