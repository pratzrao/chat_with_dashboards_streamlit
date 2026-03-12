import logging
from typing import Set, List, Dict, Any, Optional
from retrieval.bhumi_parser import BhumiChart, BhumiDashboard
from db.dbt_helpers import DbtHelper

logger = logging.getLogger(__name__)

class DashboardTableAllowlist:
    """
    Manages the allowlist of tables that the chat can access based on the current dashboard.
    Includes tables directly used by dashboard charts plus their upstream dependencies.
    """
    
    def __init__(self, dashboard_charts: List[BhumiChart] = None, dbt_helper: Optional[DbtHelper] = None):
        self.dbt_helper = dbt_helper
        self.allowed_tables: Set[str] = set()
        self.chart_tables: Set[str] = set()  # Direct chart tables
        self.upstream_tables: Set[str] = set()  # Upstream dependencies
        
        if dashboard_charts:
            self._build_allowlist(dashboard_charts)
    
    def update_for_dashboard(self, dashboard_charts: List[BhumiChart]):
        """Update allowlist for a new dashboard selection"""
        self.allowed_tables.clear()
        self.chart_tables.clear()
        self.upstream_tables.clear()
        self._build_allowlist(dashboard_charts)
    
    def _build_allowlist(self, charts: List[BhumiChart]):
        """Build the allowlist from dashboard charts and their upstream dependencies"""
        
        # Step 1: Extract direct data sources from charts
        for chart in charts:
            if chart.data_source:
                normalized_table = self._normalize_table_name(chart.data_source)
                self.chart_tables.add(normalized_table)
                self.allowed_tables.add(normalized_table)
                
                logger.debug(f"Added chart table: {normalized_table} (from chart: {chart.title})")
        
        # Step 2: Follow DBT lineage to get upstream dependencies
        if self.dbt_helper:
            for table in list(self.chart_tables):
                upstream_tables = self._get_upstream_tables(table)
                self.upstream_tables.update(upstream_tables)
                self.allowed_tables.update(upstream_tables)
        
        logger.info(f"Built allowlist with {len(self.chart_tables)} chart tables and {len(self.upstream_tables)} upstream tables")
        logger.info(f"Total allowed tables: {len(self.allowed_tables)}")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Chart tables: {sorted(self.chart_tables)}")
            logger.debug(f"Upstream tables: {sorted(self.upstream_tables)}")
    
    def _get_upstream_tables(self, table: str) -> Set[str]:
        """Get all upstream tables for a given table using DBT lineage"""
        upstream_tables = set()
        
        if not self.dbt_helper:
            return upstream_tables
        
        # Extract model name from table (handle schema.table format)
        model_name = table.split('.')[-1] if '.' in table else table
        schema_name = table.split('.')[0] if '.' in table else None
        
        # Get the model from DBT helper
        model = None
        if schema_name:
            model = self.dbt_helper.get_model_by_table(schema_name, model_name)
        else:
            model = self.dbt_helper.models.get(model_name)
        
        if not model:
            logger.debug(f"No DBT model found for table: {table}")
            return upstream_tables
        
        # Get direct upstream dependencies
        lineage = self.dbt_helper.get_lineage(model.name)
        direct_upstream = lineage.get('upstream', [])
        
        for upstream_node in direct_upstream:
            # Parse upstream node ID (format: model.database.schema.model_name)
            upstream_table = self._parse_node_id_to_table(upstream_node)
            if upstream_table:
                normalized = self._normalize_table_name(upstream_table)
                upstream_tables.add(normalized)
                logger.debug(f"Added upstream table: {normalized} (for {table})")
                
                # Recursively get upstream of upstream (with depth limit to prevent cycles)
                if len(upstream_table.split('.')) <= 3:  # Simple cycle prevention
                    recursive_upstream = self._get_upstream_tables(normalized)
                    upstream_tables.update(recursive_upstream)
        
        return upstream_tables
    
    def _parse_node_id_to_table(self, node_id: str) -> Optional[str]:
        """Parse DBT node ID to extract schema.table format"""
        # DBT node IDs are typically: model.database.schema.model_name
        parts = node_id.split('.')
        if len(parts) >= 4 and parts[0] == 'model':
            # Extract schema and model name
            schema = parts[2]
            model_name = parts[3]
            return f"{schema}.{model_name}"
        elif len(parts) >= 3:
            # Fallback: assume last two parts are schema.model
            return f"{parts[-2]}.{parts[-1]}"
        
        return None
    
    def _normalize_table_name(self, table: str) -> str:
        """Normalize table name to consistent format"""
        # Remove quotes and ensure lowercase for comparison
        table = table.strip().strip('"').strip("'")
        
        # If it doesn't have a schema, don't add one - let the system handle it
        if '.' not in table:
            return table.lower()
        
        # Split and normalize schema.table format
        parts = table.split('.')
        if len(parts) == 2:
            schema, table_name = parts
            return f"{schema.lower()}.{table_name.lower()}"
        
        return table.lower()
    
    def is_allowed(self, table_name: str) -> bool:
        """Check if a table is allowed based on the current dashboard"""
        if not self.allowed_tables:
            # If no dashboard is selected or no allowlist built, allow access
            # This maintains backward compatibility
            return True
        
        normalized = self._normalize_table_name(table_name)
        
        # Direct match
        if normalized in self.allowed_tables:
            return True
        
        # Try without schema prefix (for cases where schema is auto-added)
        table_only = normalized.split('.')[-1] if '.' in normalized else normalized
        for allowed in self.allowed_tables:
            if allowed.endswith(f".{table_only}") or allowed == table_only:
                return True
        
        # Try with common schema prefixes for the table name
        if '.' not in normalized:
            common_schemas = ['prod', 'dev_prod', 'staging', 'intermediate', 'dev_intermediate']
            for schema in common_schemas:
                candidate = f"{schema}.{normalized}"
                if candidate in self.allowed_tables:
                    return True
        
        logger.debug(f"Table {table_name} (normalized: {normalized}) not in allowlist")
        return False
    
    def get_allowed_tables(self) -> Set[str]:
        """Get the complete set of allowed tables"""
        return self.allowed_tables.copy()
    
    def get_chart_tables(self) -> Set[str]:
        """Get tables directly referenced by charts"""
        return self.chart_tables.copy()
    
    def get_upstream_tables(self) -> Set[str]:
        """Get upstream dependency tables"""
        return self.upstream_tables.copy()
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the allowlist for debugging/logging"""
        return {
            "total_allowed": len(self.allowed_tables),
            "chart_tables": len(self.chart_tables),
            "upstream_tables": len(self.upstream_tables),
            "chart_tables_list": sorted(list(self.chart_tables)),
            "upstream_tables_list": sorted(list(self.upstream_tables))
        }