import json
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class BhumiChart(BaseModel):
    """BHUMI chart structure from charts.json"""
    chart_id: str
    title: str
    chart_type: str
    chart_type_description: str
    data_source: str
    metric_calculation: str
    filters: List[str] = []
    measures: List[str] = []
    dimensions: List[str] = []
    grain: str
    x_axis: Optional[str] = None

class BhumiDashboard(BaseModel):
    """BHUMI dashboard structure"""
    dashboard_id: str
    title: str
    description: str
    charts: List[BhumiChart]

class BhumiParser:
    """Parse BHUMI-specific charts.json format"""
    
    def __init__(self, charts_json_path: str):
        self.charts_json_path = Path(charts_json_path)
        
    def parse_charts_json(self) -> Dict[str, Any]:
        """Load and parse BHUMI charts.json"""
        if not self.charts_json_path.exists():
            raise FileNotFoundError(f"Charts file not found: {self.charts_json_path}")
            
        with open(self.charts_json_path, 'r') as f:
            data = json.load(f)
            
        if "dashboards" not in data:
            raise ValueError("charts.json must have 'dashboards' array")
            
        return data
    
    def parse_dashboards(self) -> List[BhumiDashboard]:
        """Convert charts.json to structured dashboard objects"""
        data = self.parse_charts_json()
        dashboards = []
        
        for dash_data in data["dashboards"]:
            charts = []
            
            for chart_data in dash_data.get("charts", []):
                chart = BhumiChart(
                    chart_id=chart_data["chart_id"],
                    title=chart_data["title"],
                    chart_type=chart_data["chart_type"],
                    chart_type_description=chart_data["chart_type_description"],
                    data_source=chart_data["data_source"],
                    metric_calculation=chart_data["metric_calculation"],
                    filters=chart_data.get("filters", []),
                    measures=chart_data.get("measures", []),
                    dimensions=chart_data.get("dimensions", []),
                    grain=chart_data["grain"],
                    x_axis=chart_data.get("x_axis")
                )
                charts.append(chart)
            
            dashboard = BhumiDashboard(
                dashboard_id=dash_data["dashboard_id"],
                title=dash_data["title"],
                description=dash_data.get("description", ""),
                charts=charts
            )
            dashboards.append(dashboard)
            
        logger.info(f"Parsed {len(dashboards)} dashboards with {sum(len(d.charts) for d in dashboards)} charts")
        return dashboards
    
    def build_chart_lookup(self) -> Dict[str, BhumiChart]:
        """Create lookup map of chart_id -> chart object"""
        dashboards = self.parse_dashboards()
        chart_lookup = {}
        
        for dashboard in dashboards:
            for chart in dashboard.charts:
                chart_lookup[chart.chart_id] = chart
                
        return chart_lookup
    
    def extract_data_sources(self) -> List[str]:
        """Extract all unique data sources referenced by charts"""
        dashboards = self.parse_dashboards()
        data_sources = set()
        
        for dashboard in dashboards:
            for chart in dashboard.charts:
                data_sources.add(chart.data_source)
                
        return list(data_sources)
    
    def extract_programs(self) -> List[str]:
        """Auto-detect program names from chart titles and IDs"""
        dashboards = self.parse_dashboards()
        programs = set()
        
        for dashboard in dashboards:
            for chart in dashboard.charts:
                # Extract program indicators from chart titles/IDs
                title_lower = chart.title.lower()
                chart_id_lower = chart.chart_id.lower()
                
                if "ecochamp" in title_lower or "eco" in chart_id_lower:
                    programs.add("EcoChamps")
                if "fellowship" in title_lower or "fellow" in chart_id_lower:
                    programs.add("Fellowship")
                    
        return list(programs)
    
    def build_dashboard_context_graph(self) -> Dict[str, Any]:
        """Build dashboard-chart relationship graph for BHUMI"""
        dashboards = self.parse_dashboards()
        
        context_graph = {
            "dashboards": {},
            "charts": {},
            "data_sources": set()
        }
        
        for dashboard in dashboards:
            # Add dashboard to graph
            context_graph["dashboards"][dashboard.dashboard_id] = {
                "dashboard": dashboard,
                "chart_count": len(dashboard.charts),
                "charts": dashboard.charts
            }
            
            # Add charts to graph
            for chart in dashboard.charts:
                context_graph["charts"][chart.chart_id] = chart
                context_graph["data_sources"].add(chart.data_source)
        
        # Convert data_sources set to list
        context_graph["data_sources"] = list(context_graph["data_sources"])
        
        logger.info(f"Built context graph: {len(context_graph['dashboards'])} dashboards, {len(context_graph['charts'])} charts")
        return context_graph
