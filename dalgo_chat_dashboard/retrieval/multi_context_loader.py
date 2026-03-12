import os
import logging
from typing import Dict, List, Optional
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class MultiContextData:
    """Container for organizational and dashboard-specific context"""
    org_context: str
    dashboard_contexts: Dict[str, str]  # dashboard_id -> context content
    org_context_path: str
    dashboard_context_paths: Dict[str, str]  # dashboard_id -> file path

class MultiContextLoader:
    """
    Loads and manages multiple context files:
    - One organizational context file
    - One context file per dashboard
    """
    
    def __init__(self, ngo_context_folder: str):
        self.ngo_context_folder = Path(ngo_context_folder)
        self.org_context_path = self.ngo_context_folder / "org_context.md"
        self.dashboard_contexts_dir = self.ngo_context_folder / "dashboard_contexts"
        
        # Ensure directories exist
        os.makedirs(self.dashboard_contexts_dir, exist_ok=True)
        
        # Initialize with migration from old single file if needed
        self._migrate_from_single_file_if_needed()
    
    def load_all_contexts(self) -> MultiContextData:
        """Load organizational context and all dashboard contexts"""
        
        # Load organizational context
        org_context = self._load_org_context()
        
        # Load all dashboard contexts
        dashboard_contexts = {}
        dashboard_context_paths = {}
        
        if self.dashboard_contexts_dir.exists():
            for context_file in self.dashboard_contexts_dir.glob("*.md"):
                dashboard_id = context_file.stem  # filename without .md
                try:
                    with open(context_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    dashboard_contexts[dashboard_id] = content
                    dashboard_context_paths[dashboard_id] = str(context_file)
                    logger.debug(f"Loaded dashboard context for {dashboard_id}")
                except Exception as e:
                    logger.error(f"Error loading dashboard context {context_file}: {e}")
        
        logger.info(f"Loaded org context + {len(dashboard_contexts)} dashboard contexts")
        
        return MultiContextData(
            org_context=org_context,
            dashboard_contexts=dashboard_contexts,
            org_context_path=str(self.org_context_path),
            dashboard_context_paths=dashboard_context_paths
        )
    
    def get_context_for_dashboard(self, dashboard_id: Optional[str]) -> str:
        """Get combined context for a specific dashboard"""
        contexts = self.load_all_contexts()
        
        # Start with organizational context
        combined_context = contexts.org_context
        
        # Add dashboard-specific context if available
        if dashboard_id and dashboard_id in contexts.dashboard_contexts:
            dashboard_context = contexts.dashboard_contexts[dashboard_id]
            combined_context += f"\n\n# Dashboard-Specific Context: {dashboard_id}\n\n{dashboard_context}"
            logger.debug(f"Added dashboard context for {dashboard_id}")
        else:
            logger.debug(f"No specific context found for dashboard {dashboard_id}")
        
        return combined_context
    
    def _load_org_context(self) -> str:
        """Load the organizational context file"""
        try:
            if self.org_context_path.exists():
                with open(self.org_context_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                logger.warning(f"Org context file not found: {self.org_context_path}")
                return "# Organizational Context\n\nNo organizational context available."
        except Exception as e:
            logger.error(f"Error loading org context: {e}")
            return "# Organizational Context\n\nError loading organizational context."
    
    def save_org_context(self, content: str) -> bool:
        """Save organizational context"""
        try:
            with open(self.org_context_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"Saved org context to {self.org_context_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving org context: {e}")
            return False
    
    def save_dashboard_context(self, dashboard_id: str, content: str) -> bool:
        """Save dashboard-specific context"""
        try:
            dashboard_context_path = self.dashboard_contexts_dir / f"{dashboard_id}.md"
            with open(dashboard_context_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"Saved dashboard context for {dashboard_id} to {dashboard_context_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving dashboard context for {dashboard_id}: {e}")
            return False
    
    def get_dashboard_context_path(self, dashboard_id: str) -> str:
        """Get file path for dashboard context"""
        return str(self.dashboard_contexts_dir / f"{dashboard_id}.md")
    
    def dashboard_context_exists(self, dashboard_id: str) -> bool:
        """Check if dashboard context file exists"""
        dashboard_context_path = self.dashboard_contexts_dir / f"{dashboard_id}.md"
        return dashboard_context_path.exists()
    
    def create_dashboard_context(self, dashboard_id: str, initial_content: str = None) -> bool:
        """Create a new dashboard context file"""
        if self.dashboard_context_exists(dashboard_id):
            logger.warning(f"Dashboard context for {dashboard_id} already exists")
            return False
        
        if initial_content is None:
            initial_content = f"""# {dashboard_id.replace('_', ' ').title()} Dashboard Context

## Program Overview
[Describe the program/initiative that this dashboard tracks]

## Key Terminology
[Define important terms and concepts specific to this dashboard]

## Metrics Explanation
[Explain what the key metrics mean in business context]

## Data Interpretation Guidelines
[Provide guidance on how to interpret the data shown in this dashboard]

## Important Notes
[Any important caveats, data limitations, or context users should know]
"""
        
        return self.save_dashboard_context(dashboard_id, initial_content)
    
    def _migrate_from_single_file_if_needed(self):
        """Migrate from old single context file to new multi-file structure"""
        old_context_path = self.ngo_context_folder / "BHUMI_Programs_Context.md"
        
        # Only migrate if old file exists and new org context doesn't
        if old_context_path.exists() and not self.org_context_path.exists():
            logger.info("Migrating from single context file to multi-file structure")
            
            try:
                # Read the old file
                with open(old_context_path, 'r', encoding='utf-8') as f:
                    old_content = f.read()
                
                # For now, just copy the entire content to org_context.md
                # In the future, you could parse and split the content
                with open(self.org_context_path, 'w', encoding='utf-8') as f:
                    f.write(old_content)
                
                logger.info(f"Migrated context from {old_context_path} to {self.org_context_path}")
                logger.info("You can now create dashboard-specific context files and edit the org context")
                
            except Exception as e:
                logger.error(f"Error during context migration: {e}")
    
    def list_available_dashboards(self) -> List[str]:
        """List all dashboard IDs that have context files"""
        dashboard_ids = []
        if self.dashboard_contexts_dir.exists():
            for context_file in self.dashboard_contexts_dir.glob("*.md"):
                dashboard_ids.append(context_file.stem)
        return sorted(dashboard_ids)
    
    def get_context_file_info(self) -> Dict[str, any]:
        """Get information about all context files"""
        info = {
            "org_context_exists": self.org_context_path.exists(),
            "org_context_path": str(self.org_context_path),
            "dashboard_contexts": {},
            "total_dashboard_contexts": 0
        }
        
        if self.dashboard_contexts_dir.exists():
            for context_file in self.dashboard_contexts_dir.glob("*.md"):
                dashboard_id = context_file.stem
                try:
                    stat = context_file.stat()
                    info["dashboard_contexts"][dashboard_id] = {
                        "path": str(context_file),
                        "size": stat.st_size,
                        "exists": True
                    }
                except Exception:
                    info["dashboard_contexts"][dashboard_id] = {
                        "path": str(context_file),
                        "size": 0,
                        "exists": False
                    }
        
        info["total_dashboard_contexts"] = len(info["dashboard_contexts"])
        return info