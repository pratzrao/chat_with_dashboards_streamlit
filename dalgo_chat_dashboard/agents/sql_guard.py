import re
import logging
from typing import List
from agents.models import SqlValidationResult
from config import config

logger = logging.getLogger(__name__)

class SqlGuard:
    def __init__(self):
        # Forbidden keywords that could modify data or structure
        self.forbidden_keywords = {
            'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 'TRUNCATE',
            'GRANT', 'REVOKE', 'COPY', 'CALL', 'EXECUTE', 'EXEC', 'PROCEDURE',
            'FUNCTION', 'TRIGGER', 'INDEX', 'VIEW', 'SEQUENCE', 'SCHEMA',
            'DATABASE', 'TABLE', 'COLUMN', 'CONSTRAINT', 'FOREIGN', 'PRIMARY',
            'UNIQUE', 'CHECK', 'DEFAULT', 'SET', 'COMMIT', 'ROLLBACK', 'SAVEPOINT'
        }
        
        # PII-related column patterns to avoid
        self.pii_patterns = [
            r'\b(name|phone|email|address|national_id|id_number)\b',
            r'\b(contact|mobile|telephone|personal|identification)\b',
            r'\b(firstname|lastname|full_name|participant_name|survivor_name)\b'
        ]
    
    def validate_sql(self, sql: str) -> SqlValidationResult:
        """Validate SQL for safety and compliance"""
        errors = []
        warnings = []
        corrected_sql = sql.strip()
        
        # Remove comments for analysis
        sql_no_comments = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
        sql_no_comments = re.sub(r'--.*', '', sql_no_comments)
        
        # 1. Check if starts with SELECT
        sql_trimmed = sql_no_comments.strip().upper()
        if not sql_trimmed.startswith('SELECT'):
            errors.append("Query must start with SELECT")
        
        # 2. Check for forbidden keywords
        for keyword in self.forbidden_keywords:
            pattern = rf'\b{keyword}\b'
            if re.search(pattern, sql_trimmed, re.IGNORECASE):
                errors.append(f"Forbidden keyword detected: {keyword}")
        
        # 3. Check for multiple statements (semicolons)
        if ';' in sql_no_comments.rstrip(';'):  # Allow trailing semicolon
            errors.append("Multiple statements not allowed")
        
        # 4. Check for LIMIT clause (use sanitized SQL to avoid trailing semicolons)
        sanitized = self.sanitize_sql(sql_no_comments)
        sanitized_upper = sanitized.upper()
        if 'LIMIT' not in sanitized_upper:
            warnings.append("No LIMIT clause found, adding default")
            corrected_sql = f"{sanitized}\nLIMIT {config.default_limit}"
        else:
            # Validate LIMIT value
            limit_match = re.search(r'LIMIT\s+(\d+)', sanitized_upper)
            if limit_match:
                limit_value = int(limit_match.group(1))
                if limit_value > config.max_limit:
                    errors.append(f"LIMIT {limit_value} exceeds maximum allowed {config.max_limit}")
        
        # 5. Schema access warnings (informational only)
        schema_pattern = r'\b(?:staging_|intermediate_|raw_)\w+'
        if re.search(schema_pattern, sql, re.IGNORECASE):
            warnings.append("Query accesses non-production schemas")
        
        # 6. Check for potential PII access
        for pattern in self.pii_patterns:
            if re.search(pattern, sql, re.IGNORECASE):
                warnings.append(f"Query may access PII columns matching pattern: {pattern}")
        
        # 7. Check for SELECT *
        if re.search(r'SELECT\s+\*', sql_trimmed):
            warnings.append("SELECT * detected - consider specifying explicit columns")
        
        # 8. Check for forbidden schemas
        forbidden_schema_patterns = [r'\bdev_\w+\.', r'\bairbyte_internal\.', r'\becochamps25_26\.']
        for pattern in forbidden_schema_patterns:
            if re.search(pattern, sql, re.IGNORECASE):
                errors.append(f"Forbidden schema detected. Only use: prod, staging, intermediate")
        
        is_valid = len(errors) == 0
        
        return SqlValidationResult(
            is_valid=is_valid,
            corrected_sql=corrected_sql if corrected_sql != sql else None,
            errors=errors,
            warnings=warnings
        )
    
    def sanitize_sql(self, sql: str) -> str:
        """Apply basic sanitization to SQL"""
        # Remove dangerous patterns
        sanitized = sql
        
        # Remove any trailing semicolons except the last one
        sanitized = sanitized.rstrip()
        if sanitized.endswith(';'):
            sanitized = sanitized[:-1]
        
        # Ensure single statement
        if ';' in sanitized:
            # Take only the first statement
            sanitized = sanitized.split(';')[0]
        
        return sanitized.strip()
