import os
import json
from typing import List, Dict, Any
from pathlib import Path
import logging

from retrieval.ingest import Document  # Reuse existing Document class
from retrieval.bhumi_parser import BhumiParser
from retrieval.ngo_context_loader import NGOContextLoader
from db.dbt_helpers import DbtHelper

logger = logging.getLogger(__name__)

class EnhancedDocumentIngester:
    """
    Enhanced document ingester that works with any NGO context structure.
    Handles BHUMI charts.json format and generic NGO context loading.
    """
    
    def __init__(self, ngo_context_folder: str):
        self.context_loader = NGOContextLoader(ngo_context_folder)
        self.ngo_context = self.context_loader.load_context()
        
        # Initialize parsers
        self.bhumi_parser = BhumiParser(self.ngo_context.charts_json_path)
        
        # Initialize dbt helper if files exist
        self.dbt_helper = None
        try:
            self.dbt_helper = DbtHelper(
                self.ngo_context.dbt_manifest_path,
                self.ngo_context.dbt_catalog_path
            )
            logger.info(f"DBT helper initialized with {len(self.dbt_helper.models)} models")
        except Exception as e:
            logger.warning(f"DBT helper initialization failed: {e}")
    
    def ingest_all(self) -> List[Document]:
        """Ingest all documents from NGO context"""
        documents = []
        
        # 1. Ingest charts from charts.json
        chart_docs = self._ingest_charts()
        documents.extend(chart_docs)
        logger.info(f"Ingested {len(chart_docs)} chart documents")
        
        # 2. Ingest context file (NGO program explanations)
        context_docs = self._ingest_context_file()
        documents.extend(context_docs)
        logger.info(f"Ingested {len(context_docs)} context documents")
        
        # 3. Ingest dbt models (ALL models, not just chart-referenced)
        if self.dbt_helper:
            dbt_docs = self._ingest_dbt_models()
            documents.extend(dbt_docs)
            logger.info(f"Ingested {len(dbt_docs)} dbt model documents")
        
        logger.info(f"Total documents ingested: {len(documents)}")
        return documents
    
    def _ingest_charts(self) -> List[Document]:
        """Convert BHUMI charts to documents for retrieval"""
        try:
            dashboards = self.bhumi_parser.parse_dashboards()
        except Exception as e:
            logger.error(f"Failed to parse charts: {e}")
            return []
        
        documents = []
        
        for dashboard in dashboards:
            for chart in dashboard.charts:
                # Build comprehensive chart content
                content_parts = [
                    f"Chart: {chart.title}",
                    f"Type: {chart.chart_type} ({chart.chart_type_description})",
                    f"Data Source: {chart.data_source}",
                    f"Metric Calculation: {chart.metric_calculation}",
                ]
                
                if chart.filters:
                    content_parts.append(f"Filters Applied: {'; '.join(chart.filters)}")
                
                if chart.measures:
                    content_parts.append(f"Measures: {', '.join(chart.measures)}")
                
                if chart.dimensions:
                    content_parts.append(f"Dimensions: {', '.join(chart.dimensions)}")
                
                content_parts.append(f"Aggregation Level: {chart.grain}")
                
                if chart.x_axis:
                    content_parts.append(f"X-Axis: {chart.x_axis}")
                
                # Add business context based on chart details
                content_parts.append(f"Dashboard: {dashboard.title}")
                
                content = "\n".join(content_parts)
                
                doc = Document(
                    content=content,
                    metadata={
                        "type": "chart",
                        "chart_id": chart.chart_id,
                        "dashboard_id": dashboard.dashboard_id,
                        "data_source": chart.data_source,
                        "chart_type": chart.chart_type,
                        "ngo": self.ngo_context.ngo_name.lower()
                    },
                    doc_id=f"chart_{chart.chart_id}"
                )
                documents.append(doc)
        
        return documents
    
    def _ingest_context_file(self) -> List[Document]:
        """Ingest NGO context file with generic markdown chunking"""
        
        content = self.ngo_context.context_content
        if not content.strip():
            return []
        
        # Split by markdown headers (##)
        sections = content.split('\n## ')
        documents = []
        
        for i, section in enumerate(sections):
            if not section.strip():
                continue
            
            # Restore header for non-first sections
            if i > 0:
                section = "## " + section
            
            # Extract section title for metadata
            lines = section.split('\n')
            section_title = lines[0].replace('##', '').strip() if lines else f"Section {i}"
            
            doc = Document(
                content=section.strip(),
                metadata={
                    "type": "context",
                    "section_number": i,
                    "section_title": section_title,
                    "ngo": self.ngo_context.ngo_name.lower()
                },
                doc_id=f"context_section_{i}"
            )
            documents.append(doc)
        
        return documents
    
    def _ingest_dbt_models(self) -> List[Document]:
        """Ingest ALL dbt models (except test/temp)"""
        documents = []
        
        for model in self.dbt_helper.models.values():
            # Skip test and temp models
            if self._should_skip_model(model):
                continue
            
            # Build comprehensive model content
            content_parts = [
                f"DBT Model: {model.name}",
                f"Schema: {model.schema}",
                f"Database: {model.database}",
                f"Description: {model.description or 'No description available'}"
            ]
            
            # Add column information
            if model.columns:
                columns_info = []
                for col in model.columns[:30]:  # Limit to first 30 columns
                    col_info = f"{col.name} ({col.type})"
                    if col.description:
                        col_info += f" - {col.description}"
                    columns_info.append(col_info)
                content_parts.append(f"Columns: {'; '.join(columns_info)}")
            
            # Add lineage information
            lineage = self.dbt_helper.get_lineage(model.name)
            if lineage.get("upstream"):
                content_parts.append(f"Built from: {', '.join(lineage['upstream'])}")
            if lineage.get("downstream"):
                content_parts.append(f"Used by: {', '.join(lineage['downstream'])}")
            
            content = "\n".join(content_parts)
            
            doc = Document(
                content=content,
                metadata={
                    "type": "dbt_model",
                    "model": model.name,
                    "schema": model.schema,
                    "table_name": model.name,
                    "database": model.database,
                    "ngo": self.ngo_context.ngo_name.lower()
                },
                doc_id=f"dbt_model_{model.schema}.{model.name}"
            )
            documents.append(doc)
        
        return documents
    
    def _should_skip_model(self, model) -> bool:
        """Determine if dbt model should be skipped from vectorization"""

        # Skip obvious temp/test only
        if model.name.endswith('_test') or '_test_' in model.name:
            return True
        if model.name.startswith(('temp_', 'tmp_')):
            return True
        # Skip raw/airbyte/internal schemas (noise, not for answering)
        schema_lower = (model.schema or "").lower()
        if schema_lower.startswith("airbyte_internal") or schema_lower.startswith("raw"):
            return True
        return False
    
    def get_dashboard_context_graph(self) -> Dict[str, Any]:
        """Get dashboard context graph for UI"""
        return self.bhumi_parser.build_dashboard_context_graph()
    
    def get_data_sources(self) -> List[str]:
        """Get all data sources referenced by charts"""
        return self.bhumi_parser.extract_data_sources()
    
    def get_programs(self) -> List[str]:
        """Get program names auto-detected from context"""
        return self.bhumi_parser.extract_programs()
