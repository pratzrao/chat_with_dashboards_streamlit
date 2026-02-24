import os
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

class NGOContext(BaseModel):
    """Complete NGO context loaded from standardized folder structure"""
    ngo_name: str
    charts_data: Dict[str, Any]
    charts_json_path: str
    dbt_manifest_path: str
    dbt_catalog_path: str
    context_file_path: str
    context_content: str

class NGOContextLoader:
    """
    Generic loader for any NGO context following the standard structure:
    
    {ngo_name}_context/
    ├── dashboard_json/charts.json
    ├── {dbt_folder}/manifest.json & catalog.json  
    ├── {NGO_NAME}_Programs_Context.md
    └── config.json (optional)
    """
    
    def __init__(self, context_folder: str):
        self.context_folder = Path(context_folder)
        self.ngo_name = self._extract_ngo_name()
        
    def _extract_ngo_name(self) -> str:
        """Extract NGO name from context folder name"""
        folder_name = self.context_folder.name.lower()
        if folder_name.endswith('_context'):
            return folder_name.replace('_context', '').upper()
        return folder_name.upper()
    
    def load_context(self) -> NGOContext:
        """Load complete NGO context from folder structure"""
        try:
            # Load charts.json
            charts_data = self._load_charts_json()
            
            # Find dbt files (auto-detect folder)
            dbt_manifest, dbt_catalog = self._find_dbt_files()
            
            # Load context file (auto-detect)
            context_file, context_content = self._load_context_file()
            
            logger.info(f"Successfully loaded {self.ngo_name} context")
            
            charts_json_path = str(self.context_folder / "dashboard_json" / "charts.json")
            
            return NGOContext(
                ngo_name=self.ngo_name,
                charts_data=charts_data,
                charts_json_path=charts_json_path,
                dbt_manifest_path=dbt_manifest,
                dbt_catalog_path=dbt_catalog, 
                context_file_path=context_file,
                context_content=context_content
            )
            
        except Exception as e:
            logger.error(f"Failed to load NGO context from {self.context_folder}: {e}")
            raise
    
    def _load_charts_json(self) -> Dict[str, Any]:
        """Load and validate charts.json"""
        charts_path = self.context_folder / "dashboard_json" / "charts.json"
        
        if not charts_path.exists():
            raise FileNotFoundError(f"charts.json not found at {charts_path}")
            
        with open(charts_path, 'r') as f:
            charts_data = json.load(f)
            
        # Validate structure
        if "dashboards" not in charts_data:
            raise ValueError("charts.json must have 'dashboards' key")
            
        logger.info(f"Loaded {len(charts_data['dashboards'])} dashboards from charts.json")
        return charts_data
    
    def _find_dbt_files(self) -> tuple[str, str]:
        """Auto-detect dbt manifest.json and catalog.json files"""
        possible_dbt_folders = []
        
        # Look for folders containing 'dbt' in name
        for item in self.context_folder.iterdir():
            if item.is_dir() and 'dbt' in item.name.lower():
                possible_dbt_folders.append(item)
        
        # If no dbt folder found, check root level
        if not possible_dbt_folders:
            possible_dbt_folders = [self.context_folder]
            
        # Find manifest.json and catalog.json
        manifest_path = None
        catalog_path = None
        
        for folder in possible_dbt_folders:
            manifest_candidate = folder / "manifest.json"
            catalog_candidate = folder / "catalog.json"
            
            if manifest_candidate.exists():
                manifest_path = str(manifest_candidate)
            if catalog_candidate.exists():
                catalog_path = str(catalog_candidate)
                
        if not manifest_path:
            raise FileNotFoundError(f"manifest.json not found in {self.context_folder}")
        if not catalog_path:
            raise FileNotFoundError(f"catalog.json not found in {self.context_folder}")
            
        logger.info(f"Found dbt files: {manifest_path}, {catalog_path}")
        return manifest_path, catalog_path
    
    def _load_context_file(self) -> tuple[str, str]:
        """Auto-detect and load the main context markdown file"""
        # Look for {NGO_NAME}_Programs_Context.md or similar
        possible_patterns = [
            f"{self.ngo_name}_Programs_Context.md",
            f"{self.ngo_name}_Context.md", 
            f"{self.ngo_name.lower()}_context.md",
            "context.md",
            "programs_context.md"
        ]
        
        context_path = None
        for pattern in possible_patterns:
            candidate = self.context_folder / pattern
            if candidate.exists():
                context_path = candidate
                break
                
        # If no exact match, find any .md file 
        if not context_path:
            md_files = list(self.context_folder.glob("*.md"))
            if md_files:
                context_path = md_files[0]  # Take first .md file found
                
        if not context_path:
            raise FileNotFoundError(f"No context .md file found in {self.context_folder}")
            
        # Load content
        with open(context_path, 'r') as f:
            content = f.read()
            
        logger.info(f"Loaded context file: {context_path}")
        return str(context_path), content
    
    def validate_context_structure(self) -> Dict[str, bool]:
        """Validate that context folder has required components"""
        checks = {
            "charts_json_exists": (self.context_folder / "dashboard_json" / "charts.json").exists(),
            "dbt_files_exist": False,
            "context_file_exists": False
        }
        
        # Check for dbt files
        try:
            self._find_dbt_files()
            checks["dbt_files_exist"] = True
        except FileNotFoundError:
            pass
            
        # Check for context file
        try:
            self._load_context_file()
            checks["context_file_exists"] = True  
        except FileNotFoundError:
            pass
            
        return checks