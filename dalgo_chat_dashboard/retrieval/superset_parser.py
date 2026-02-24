import os
import yaml
from typing import Dict, List, Any, Optional
from pydantic import BaseModel

class Chart(BaseModel):
    chart_id: int
    slice_name: str
    description: Optional[str] = ""
    viz_type: str
    dataset_id: str
    datasource: str
    metrics: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    params: Dict[str, Any] = {}
    query_context: Optional[str] = ""

class Dataset(BaseModel):
    dataset_id: str
    table_name: str
    schema_name: str  # Renamed to avoid Pydantic conflict
    catalog: str
    main_dttm_col: Optional[str] = ""
    description: Optional[str] = ""
    metrics: List[Dict[str, Any]] = []
    columns: List[Dict[str, Any]] = []

class Dashboard(BaseModel):
    dashboard_id: str
    dashboard_title: str
    description: Optional[str] = ""
    uuid: str
    chart_ids: List[int] = []
    position_data: Dict[str, Any] = {}

class SupersetParser:
    def __init__(self, export_dir: str):
        self.export_dir = export_dir
        self.charts_dir = os.path.join(export_dir, "charts")
        self.dashboards_dir = os.path.join(export_dir, "dashboards")
        self.datasets_dir = os.path.join(export_dir, "datasets")
        
    def parse_dashboards(self) -> List[Dashboard]:
        dashboards = []
        for filename in os.listdir(self.dashboards_dir):
            if filename.endswith('.yaml'):
                with open(os.path.join(self.dashboards_dir, filename), 'r') as f:
                    data = yaml.safe_load(f)
                
                # Extract chart IDs from position data
                chart_ids = []
                for key, value in data.get('position', {}).items():
                    if key.startswith('CHART-') and 'meta' in value and 'chartId' in value['meta']:
                        chart_ids.append(value['meta']['chartId'])
                
                dashboard = Dashboard(
                    dashboard_id=filename.replace('.yaml', ''),
                    dashboard_title=data.get('dashboard_title', ''),
                    description=data.get('description', ''),
                    uuid=data.get('uuid', ''),
                    chart_ids=chart_ids,
                    position_data=data.get('position', {})
                )
                dashboards.append(dashboard)
        return dashboards
    
    def parse_charts(self) -> List[Chart]:
        charts = []
        for filename in os.listdir(self.charts_dir):
            if filename.endswith('.yaml'):
                with open(os.path.join(self.charts_dir, filename), 'r') as f:
                    data = yaml.safe_load(f)
                
                # Extract chart ID from filename
                chart_id = int(filename.split('_')[-1].replace('.yaml', ''))
                
                chart = Chart(
                    chart_id=chart_id,
                    slice_name=data.get('slice_name', ''),
                    description=data.get('description', ''),
                    viz_type=data.get('viz_type', ''),
                    dataset_id=str(data.get('params', {}).get('datasource', '')),
                    datasource=str(data.get('params', {}).get('datasource', '')),
                    metrics=data.get('params', {}).get('metrics', []),
                    filters=data.get('params', {}).get('adhoc_filters', []),
                    params=data.get('params', {}),
                    query_context=data.get('query_context', '')
                )
                charts.append(chart)
        return charts
    
    def parse_datasets(self) -> List[Dataset]:
        datasets = []
        # Navigate the datasets directory structure
        for db_dir in os.listdir(self.datasets_dir):
            db_path = os.path.join(self.datasets_dir, db_dir)
            if os.path.isdir(db_path):
                for filename in os.listdir(db_path):
                    if filename.endswith('.yaml'):
                        with open(os.path.join(db_path, filename), 'r') as f:
                            data = yaml.safe_load(f)
                        
                        dataset = Dataset(
                            dataset_id=filename.replace('.yaml', ''),
                            table_name=data.get('table_name', ''),
                            schema_name=data.get('schema', ''),
                            catalog=data.get('catalog', ''),
                            main_dttm_col=data.get('main_dttm_col', ''),
                            description=data.get('description', ''),
                            metrics=data.get('metrics', []),
                            columns=data.get('columns', [])
                        )
                        datasets.append(dataset)
        return datasets
    
    def build_dashboard_context_graph(self) -> Dict[str, Any]:
        dashboards = self.parse_dashboards()
        charts = self.parse_charts()
        datasets = self.parse_datasets()
        
        # Create lookup maps
        charts_by_id = {chart.chart_id: chart for chart in charts}
        datasets_by_id = {dataset.dataset_id: dataset for dataset in datasets}
        
        context_graph = {
            "dashboards": {},
            "charts": charts_by_id,
            "datasets": datasets_by_id
        }
        
        for dashboard in dashboards:
            dashboard_charts = []
            for chart_id in dashboard.chart_ids:
                if chart_id in charts_by_id:
                    chart = charts_by_id[chart_id]
                    dashboard_charts.append({
                        "chart": chart,
                        "dataset": datasets_by_id.get(chart.dataset_id)
                    })
            
            context_graph["dashboards"][dashboard.dashboard_id] = {
                "dashboard": dashboard,
                "charts": dashboard_charts
            }
        
        return context_graph
