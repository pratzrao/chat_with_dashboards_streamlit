import os
import streamlit as st
from typing import Optional
from pydantic import BaseModel
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

class Config(BaseModel):
    # OpenAI
    openai_api_key: str
    
    # Postgres
    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_password: str
    
    # NGO Context (NEW - replaces individual paths)
    ngo_context_folder: str
    charts_json_path: str
    dbt_manifest_path: str
    dbt_catalog_path: str
    context_file_path: str
    
    # Legacy paths (for backwards compatibility)
    superset_export_dir: Optional[str] = None
    
    # App settings
    default_limit: int = 500
    max_limit: int = 2000
    sql_timeout: int = 15
    strict_mode: bool = True
    demo_mode: bool = False
    
    @classmethod
    def from_env(cls) -> "Config":
        def get_config_value(key: str, default=None):
            """Get config value from Streamlit secrets first, then environment"""
            try:
                # Try Streamlit secrets first
                if hasattr(st, 'secrets') and key in st.secrets:
                    return st.secrets[key]
            except Exception:
                # Fallback to environment variable if secrets not available
                pass
            return os.getenv(key, default)
        
        # Resolve base directory (repo root relative to this file)
        base_dir = Path(__file__).resolve().parent

        # NGO context folder (NEW approach)
        ngo_context_raw = get_config_value("NGO_CONTEXT_FOLDER", "../bhumi_context")
        ngo_context_path = Path(ngo_context_raw)
        if not ngo_context_path.is_absolute():
            ngo_context_path = (base_dir / ngo_context_path).resolve()
        ngo_context = str(ngo_context_path)
        
        pg_port_env = get_config_value("LOCAL_TUNNEL_PORT", get_config_value("PG_PORT", "5432"))

        return cls(
            openai_api_key=get_config_value("OPENAI_API_KEY"),
            pg_host=get_config_value("PG_HOST", "localhost"),
            pg_port=int(pg_port_env),
            pg_database=get_config_value("PG_DATABASE"),
            pg_user=get_config_value("PG_USER"),
            pg_password=get_config_value("PG_PASSWORD"),
            
            # NGO Context paths (auto-constructed)
            ngo_context_folder=ngo_context,
            charts_json_path=str(ngo_context_path / "dashboard_json" / "charts.json"),
            dbt_manifest_path=str(ngo_context_path / "bhumi_dbt" / "manifest.json"),
            dbt_catalog_path=str(ngo_context_path / "bhumi_dbt" / "catalog.json"),
            context_file_path=str(ngo_context_path / "BHUMI_Programs_Context.md"),
            
            # Legacy (fallback to old paths if NGO context not available)
            superset_export_dir=get_config_value("SUPERSET_EXPORT_DIR", "../deprecated_shofco_context"),
            
            default_limit=int(get_config_value("DEFAULT_LIMIT", "500")),
            max_limit=int(get_config_value("MAX_LIMIT", "2000")),
            sql_timeout=int(get_config_value("SQL_TIMEOUT", "15")),
            strict_mode=get_config_value("STRICT_MODE", "true").lower() == "true",
            demo_mode=get_config_value("DEMO_MODE", "false").lower() == "true"
        )

config = Config.from_env()
