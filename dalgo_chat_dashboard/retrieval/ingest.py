import os
import json
from typing import List, Dict, Any
from pydantic import BaseModel
from retrieval.superset_parser import SupersetParser, Dashboard, Chart, Dataset

class Document(BaseModel):
    content: str
    metadata: Dict[str, Any]
    doc_id: str

class DocumentIngester:
    def __init__(self, export_dir: str, context_file_path: str):
        self.superset_parser = SupersetParser(export_dir)
        self.context_file_path = context_file_path
    
    def ingest_all(self) -> List[Document]:
        """Ingest all data sources into documents"""
        documents = []
        
        # Ingest charts
        documents.extend(self._ingest_charts())
        
        # Ingest datasets  
        documents.extend(self._ingest_datasets())
        
        # Ingest context file
        documents.extend(self._ingest_context_file())
        
        return documents
    
    def _ingest_charts(self) -> List[Document]:
        """Convert charts to documents for retrieval"""
        charts = self.superset_parser.parse_charts()
        documents = []
        
        for chart in charts:
            # Build content string
            content_parts = [
                f"Chart: {chart.slice_name}",
                f"Type: {chart.viz_type}",
                f"Dataset: {chart.dataset_id}"
            ]
            
            if chart.description:
                content_parts.append(f"Description: {chart.description}")
            
            # Add metrics info
            if chart.metrics:
                metrics_text = []
                for metric in chart.metrics:
                    if isinstance(metric, dict):
                        metric_label = metric.get('label', str(metric))
                        metrics_text.append(metric_label)
                content_parts.append(f"Metrics: {', '.join(metrics_text)}")
            
            # Add filter info
            if chart.filters:
                filters_text = []
                for filter_item in chart.filters:
                    if isinstance(filter_item, dict):
                        subject = filter_item.get('subject', '')
                        operator = filter_item.get('operator', '')
                        comparator = filter_item.get('comparator', '')
                        filters_text.append(f"{subject} {operator} {comparator}")
                content_parts.append(f"Filters: {'; '.join(filters_text)}")

            # Add full params + query context for exact chart SQL logic
            if chart.params:
                params_json = json.dumps(chart.params, indent=2, sort_keys=True)
                content_parts.append(f"Chart Params (JSON):\n{params_json}")

            if chart.query_context:
                content_parts.append(f"Chart Query Context (JSON):\n{chart.query_context}")
            
            content = "\n".join(content_parts)
            
            doc = Document(
                content=content,
                metadata={
                    "type": "chart",
                    "chart_id": str(chart.chart_id),
                    "slice_name": str(chart.slice_name),
                    "viz_type": str(chart.viz_type),
                    "dataset_id": str(chart.dataset_id)
                },
                doc_id=f"chart_{chart.chart_id}"
            )
            documents.append(doc)
        
        return documents
    
    def _ingest_datasets(self) -> List[Document]:
        """Convert datasets to documents for retrieval"""
        datasets = self.superset_parser.parse_datasets()
        documents = []
        
        for dataset in datasets:
            content_parts = [
                f"Dataset: {dataset.table_name}",
                f"Schema: {dataset.schema}",
                f"Catalog: {dataset.catalog}"
            ]
            
            if dataset.description:
                content_parts.append(f"Description: {dataset.description}")
            
            if dataset.main_dttm_col:
                content_parts.append(f"Main Date Column: {dataset.main_dttm_col}")
            
            # Add metrics info
            if dataset.metrics:
                metrics_text = []
                for metric in dataset.metrics:
                    metric_name = metric.get('metric_name', '')
                    verbose_name = metric.get('verbose_name', '')
                    expression = metric.get('expression', '')
                    
                    metric_info = f"{verbose_name or metric_name}"
                    if expression:
                        metric_info += f" (calculated as: {expression})"
                    metrics_text.append(metric_info)
                
                content_parts.append(f"Available Metrics: {'; '.join(metrics_text)}")
            
            content = "\n".join(content_parts)
            
            doc = Document(
                content=content,
                metadata={
                    "type": "dataset",
                    "dataset_id": str(dataset.dataset_id),
                    "table_name": str(dataset.table_name),
                    "schema": str(dataset.schema_name),
                    "catalog": str(dataset.catalog)
                },
                doc_id=f"dataset_{dataset.dataset_id}"
            )
            documents.append(doc)
        
        return documents
    
    def _ingest_context_file(self) -> List[Document]:
        """Ingest the human context file"""
        if not os.path.exists(self.context_file_path):
            return []
        
        with open(self.context_file_path, 'r') as f:
            content = f.read()
        
        # Simple chunking - split by sections (##)
        sections = content.split('\n## ')
        documents = []
        
        for i, section in enumerate(sections):
            if not section.strip():
                continue
            
            # Add back the ## prefix if it's not the first section
            if i > 0:
                section = "## " + section
            
            doc = Document(
                content=section.strip(),
                metadata={
                    "type": "context",
                    "section_number": str(i),
                    "source": "shofco_gender_context"
                },
                doc_id=f"context_section_{i}"
            )
            documents.append(doc)
        
        return documents
    
    def get_dashboard_context_graph(self) -> Dict[str, Any]:
        """Get the dashboard-chart-dataset relationship graph"""
        return self.superset_parser.build_dashboard_context_graph()
