import psycopg2
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
import logging
from contextlib import contextmanager
from config import config

logger = logging.getLogger(__name__)

class PostgresExecutor:
    def __init__(self):
        self.connection_params = {
            'host': config.pg_host,
            'port': config.pg_port,
            'database': config.pg_database,
            'user': config.pg_user,
            'password': config.pg_password,
            'sslmode': 'require'  # Force SSL even through tunnel
        }
    
    @contextmanager
    def get_connection(self):
        conn = None
        try:
            conn = psycopg2.connect(**self.connection_params)
            conn.set_session(autocommit=True)
            # Set statement timeout
            with conn.cursor() as cursor:
                cursor.execute(f"SET statement_timeout = '{config.sql_timeout}s'")
            yield conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def test_connection(self) -> bool:
        """Test if database connection works"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    return True
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
    
    def execute_sql(self, sql: str) -> Dict[str, Any]:
        """Execute SQL and return results with metadata"""
        try:
            with self.get_connection() as conn:
                df = pd.read_sql_query(sql, conn)
                
                return {
                    'success': True,
                    'dataframe': df,
                    'row_count': len(df),
                    'columns': list(df.columns),
                    'rows': df.to_dict(orient="records"),
                    'error': None
                }
        except Exception as e:
            logger.error(f"SQL execution error: {e}")
            return {
                'success': False,
                'dataframe': None,
                'row_count': 0,
                'columns': [],
                'rows': [],
                'error': str(e)
            }

    def get_table_columns_live(self, schema: str, table: str) -> List[Dict[str, str]]:
        """Fetch column metadata for a single table directly from information_schema."""
        sql = """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """
        try:
            with self.get_connection() as conn:
                df = pd.read_sql_query(sql, conn, params=(schema, table))
            cols = []
            for _, row in df.iterrows():
                cols.append({
                    "name": row["column_name"],
                    "type": row["data_type"],
                    "nullable": row["is_nullable"] == "YES"
                })
            return cols
        except Exception as e:
            logger.warning(f"Live column fetch failed for {schema}.{table}: {e}")
            return []
    
    def get_schema_info(self, schema: str = None) -> Dict[str, List[Dict[str, str]]]:
        """Get table and column information from information_schema"""
        schema_filter = f"AND table_schema = '{schema}'" if schema else ""
        
        sql = f"""
        SELECT 
            table_schema,
            table_name,
            column_name,
            data_type,
            is_nullable
        FROM information_schema.columns 
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'pg_toast', 'airbyte_internal')
        AND table_schema IN ('prod', 'staging', 'intermediate')
        AND table_schema NOT LIKE 'dev_%'
        {schema_filter}
        ORDER BY table_schema, table_name, ordinal_position
        """
        
        result = self.execute_sql(sql)
        if not result['success']:
            return {}
        
        df = result['dataframe']
        schema_info = {}
        
        for _, row in df.iterrows():
            schema_name = row['table_schema']
            table_name = row['table_name']
            key = f"{schema_name}.{table_name}"
            
            if key not in schema_info:
                schema_info[key] = []
            
            column_info = {
                'name': row['column_name'],
                'type': row['data_type'],
                'nullable': row['is_nullable'] == 'YES'
            }
            
            # Sample values disabled on startup to avoid extra SQL load
            
            schema_info[key].append(column_info)
        
        return schema_info
    
    def _get_sample_values(self, table_name: str, column_name: str, limit: int = 10) -> List[str]:
        """Get sample distinct values for a column to help with query generation"""
        try:
            sql = f"""
            SELECT DISTINCT "{column_name}" 
            FROM {table_name} 
            WHERE "{column_name}" IS NOT NULL 
            ORDER BY "{column_name}" 
            LIMIT {limit}
            """
            
            result = self.execute_sql(sql)
            if result['success'] and not result['dataframe'].empty:
                return [str(val) for val in result['dataframe'].iloc[:, 0].tolist() if val is not None]
            
        except Exception as e:
            logger.debug(f"Could not get sample values for {table_name}.{column_name}: {e}")
        
        return []

    def get_sample_values(self, table_name: str, column_name: str, limit: int = 10) -> List[str]:
        """Public wrapper for safe sample value retrieval (read-only)."""
        # Basic sanitization: require schema.table and simple column identifier
        if "." not in table_name:
            raise ValueError("table_name must be schema.table")
        if not column_name.replace("_", "").isalnum():
            raise ValueError("column_name must be alphanumeric/underscore")
        return self._get_sample_values(table_name, column_name, limit)

    def get_distinct_values(self, table_name: str, column_name: str, limit: int = 50) -> List[str]:
        """Fetch distinct values for a column (read-only)."""
        return self.get_sample_values(table_name, column_name, limit)

class SchemaIndex:
    def __init__(self, postgres_executor: PostgresExecutor):
        self.postgres = postgres_executor
        self._schema_cache = {}
        self._load_schema_cache()
    
    def _load_schema_cache(self):
        """Load schema information and cache it"""
        try:
            self._schema_cache = self.postgres.get_schema_info()
            logger.info(f"Loaded schema info for {len(self._schema_cache)} tables")
        except Exception as e:
            logger.warning(f"Failed to load schema cache: {e}")
            # Provide fallback schema for prod_gender
            self._schema_cache = {
                "prod_gender.case_occurence": [
                    {"name": "case_id", "type": "text", "nullable": False},
                    {"name": "date_of_case_reporting", "type": "date", "nullable": True},
                    {"name": "district", "type": "text", "nullable": True},
                    {"name": "survivor_id", "type": "text", "nullable": True}
                ],
                "prod_gender.champions": [
                    {"name": "champion_id", "type": "text", "nullable": False},
                    {"name": "district", "type": "text", "nullable": True}
                ]
            }
    
    def get_table_columns(self, table: str) -> List[Dict[str, str]]:
        """Get columns for a table (schema.table format)"""
        cols = self._schema_cache.get(table)
        if cols:
            return cols
        # Try live fetch if not cached
        if "." in table:
            schema, tbl = table.split(".", 1)
            live_cols = self.postgres.get_table_columns_live(schema, tbl)
            if live_cols:
                self._schema_cache[table] = live_cols
                return live_cols
        return []
    
    def list_tables(self, schema: str = None) -> List[str]:
        """List all tables, optionally filtered by schema"""
        if schema:
            return [table for table in self._schema_cache.keys() 
                   if table.startswith(f"{schema}.")]
        return list(self._schema_cache.keys())
    
    def table_exists(self, table: str) -> bool:
        """Check if a table exists"""
        if table in self._schema_cache:
            return True
        if "." in table:
            schema, tbl = table.split(".", 1)
            cols = self.postgres.get_table_columns_live(schema, tbl)
            if cols:
                self._schema_cache[table] = cols
                return True
        return False
    
    def find_tables_by_pattern(self, pattern: str) -> List[str]:
        """Find tables matching a pattern"""
        pattern_lower = pattern.lower()
        return [table for table in self._schema_cache.keys() 
                if pattern_lower in table.lower()]
