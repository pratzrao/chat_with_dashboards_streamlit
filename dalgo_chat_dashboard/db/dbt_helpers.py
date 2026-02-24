import json
from typing import Dict, List, Any, Optional
from pydantic import BaseModel

class DbtColumn(BaseModel):
    name: str
    type: str
    description: str = ""

class DbtModel(BaseModel):
    name: str
    schema: str
    database: str
    description: str = ""
    columns: List[DbtColumn] = []
    upstream: List[str] = []
    downstream: List[str] = []

class DbtHelper:
    def __init__(self, manifest_path: str, catalog_path: str):
        with open(manifest_path, 'r') as f:
            self.manifest = json.load(f)
        with open(catalog_path, 'r') as f:
            self.catalog = json.load(f)
        
        self._build_model_index()
    
    def _build_model_index(self):
        self.models = {}
        self.lineage_map = {}
        
        # Build models from manifest
        for node_id, node in self.manifest.get('nodes', {}).items():
            if node.get('resource_type') == 'model':
                model_name = node.get('name', '')
                schema = node.get('schema', '')
                database = node.get('database', '')
                description = node.get('description', '')
                
                # Get columns from catalog
                columns = []
                catalog_key = f"{database}.{schema}.{model_name}"
                if catalog_key in self.catalog.get('nodes', {}):
                    catalog_node = self.catalog['nodes'][catalog_key]
                    for col_name, col_data in catalog_node.get('columns', {}).items():
                        columns.append(DbtColumn(
                            name=col_name,
                            type=col_data.get('type', ''),
                            description=col_data.get('comment', '')
                        ))
                
                # Get lineage
                upstream = [dep for dep in node.get('depends_on', {}).get('nodes', [])]
                
                model = DbtModel(
                    name=model_name,
                    schema=schema,
                    database=database,
                    description=description,
                    columns=columns,
                    upstream=upstream
                )
                
                self.models[model_name] = model
                self.lineage_map[model_name] = {
                    'upstream': upstream,
                    'downstream': []
                }
        
        # Build downstream lineage
        for model_name, lineage in self.lineage_map.items():
            for upstream_node in lineage['upstream']:
                upstream_name = upstream_node.split('.')[-1]  # Extract model name
                if upstream_name in self.lineage_map:
                    self.lineage_map[upstream_name]['downstream'].append(model_name)
    
    def find_models(self, query: str, program_id: Optional[str] = None) -> List[DbtModel]:
        """Find models based on query string"""
        results = []
        query_lower = query.lower()
        
        for model in self.models.values():
            # Check name, description, schema for matches
            if (query_lower in model.name.lower() or 
                query_lower in model.description.lower() or
                query_lower in model.schema.lower()):
                results.append(model)
            
            # Check columns
            for column in model.columns:
                if (query_lower in column.name.lower() or 
                    query_lower in column.description.lower()):
                    results.append(model)
                    break
        
        # Filter by program if specified
        if program_id:
            results = [m for m in results if program_id in m.schema.lower()]
        
        # Deduplicate by model name while preferring production schemas
        def rank(model: DbtModel) -> int:
            schema_lower = model.schema.lower()
            if schema_lower.startswith("prod"):
                return 0
            if "prod" in schema_lower:
                return 1
            return 2

        sorted_results = sorted(results, key=lambda m: (rank(m), m.schema, m.name))

        seen = set()
        unique: List[DbtModel] = []
        for m in sorted_results:
            if m.name not in seen:
                seen.add(m.name)
                unique.append(m)
        return unique
    
    def get_columns(self, model_or_relation: str) -> List[DbtColumn]:
        """Get columns for a model or table relation"""
        if model_or_relation in self.models:
            return self.models[model_or_relation].columns
        
        # Try to find by table name
        for model in self.models.values():
            if f"{model.schema}.{model.name}" == model_or_relation:
                return model.columns
        
        return []
    
    def get_lineage(self, model: str) -> Dict[str, List[str]]:
        """Get upstream and downstream dependencies for a model"""
        if model in self.lineage_map:
            return self.lineage_map[model]
        return {'upstream': [], 'downstream': []}
    
    def get_model_by_table(self, schema: str, table: str) -> Optional[DbtModel]:
        """Find model by schema.table"""
        for model in self.models.values():
            if model.schema == schema and model.name == table:
                return model
        return None
    
    def get_schema_tables(self, schema: str) -> List[str]:
        """Get all tables in a schema"""
        tables = []
        for model in self.models.values():
            if model.schema == schema:
                tables.append(model.name)
        return tables
