"""
Hardcoded Value Detector

Static analysis tool that scans Python code for hardcoded values that should
be using environment config variables instead.

Usage:
    python utils/hardcoded_checker.py [--fix] [path]
    
    Or import and run:
        from utils.hardcoded_checker import run_hardcoded_check
        issues = run_hardcoded_check()

This complements runtime_config_checker.py by catching config bypasses at the
code level, not just at resolution time.
"""

import os
import re
import ast
import logging
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Map of hardcoded patterns to their expected config sources
# Format: "hardcoded_value": ("expected_config_key", "description")
HARDCODED_PATTERNS: Dict[str, Tuple[str, str]] = {
    # Database tables
    "rag_queries": ("env_config.rag_queries_table", "RAG queries table name"),
    "rag_queries_dev": ("env_config.rag_queries_table", "RAG queries dev table name"),
    "votes": ("env_config.votes_table", "Votes table name"),
    "votes_dev": ("env_config.votes_table", "Votes dev table name"),
    "feedback": ("env_config.feedback_table", "Feedback table name"),
    "feedback_dev": ("env_config.feedback_table", "Feedback dev table name"),
    
    # Model names - should use config
    "gpt-4o": ("CHAT_DEPLOYMENT or env_config.model_name", "Chat model deployment"),
    "gpt-4o-prod": ("CHAT_DEPLOYMENT or env_config.model_name", "Chat model deployment"),
    "gpt-35-turbo": ("CHAT_DEPLOYMENT or env_config.model_name", "Chat model deployment"),
    
    # Search index
    "vector-rag": ("AZURE_SEARCH_INDEX", "Search index name"),
}

# Patterns that are OK to use literally (false positive exclusions)
ALLOWED_CONTEXTS = [
    r"table_name\s*=\s*['\"]",  # Variable assignment from config
    r"def\s+\w+.*['\"]",  # Default parameter values
    r"#.*",  # Comments
    r"logger\.",  # Log messages
    r"print\(",  # Print statements
    r"\"\"\"",  # Docstrings
    r"f?['\"].*{.*}.*['\"]",  # f-strings with variables (partial check)
    r"\.env\.example",  # .env.example file references
    r"information_schema",  # Schema queries checking table existence
]


@dataclass
class HardcodedIssue:
    """Represents a detected hardcoded value issue."""
    file_path: str
    line_number: int
    line_content: str
    hardcoded_value: str
    expected_config: str
    description: str
    severity: str = "warning"


def should_skip_line(line: str, pattern: str) -> bool:
    """Check if a line should be skipped (false positive contexts)."""
    # Skip comments
    stripped = line.strip()
    if stripped.startswith("#"):
        return True
    
    # Skip if it's in information_schema query (checking table existence is OK)
    if "information_schema" in line.lower():
        return True
    
    # Skip if it's in a log message
    if "logger." in line or "logging." in line:
        return True
    
    # Skip if the value is being assigned FROM a config
    if f"= env_config." in line or f"= config." in line:
        return True
    
    # Skip if it's a comparison for table name checking (not an INSERT/CREATE)
    if f"== '{pattern}'" in line or f"== \"{pattern}\"" in line:
        return True
    
    return False


def scan_file(file_path: Path, patterns: Dict[str, Tuple[str, str]]) -> List[HardcodedIssue]:
    """Scan a single Python file for hardcoded values."""
    issues = []
    
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()
    except Exception as e:
        logger.warning(f"Could not read {file_path}: {e}")
        return issues
    
    for line_num, line in enumerate(lines, start=1):
        for pattern, (expected_config, description) in patterns.items():
            # Check if this hardcoded value appears in the line
            # Look for it in SQL statements, table references, etc.
            
            # Pattern: table name in SQL (INSERT INTO, CREATE TABLE, ALTER TABLE, FROM, etc.)
            sql_patterns = [
                rf"INSERT\s+INTO\s+{pattern}\b",
                rf"CREATE\s+TABLE\s+{pattern}\b",
                rf"ALTER\s+TABLE\s+{pattern}\b",
                rf"FROM\s+{pattern}\b",
                rf"UPDATE\s+{pattern}\b",
                rf"DELETE\s+FROM\s+{pattern}\b",
                rf"table_name\s*=\s*['\"]?{pattern}['\"]?",
            ]
            
            for sql_pattern in sql_patterns:
                if re.search(sql_pattern, line, re.IGNORECASE):
                    if not should_skip_line(line, pattern):
                        # Check if it's using a variable (f-string with {table_name})
                        if "{" in line and "table_name" in line.lower():
                            continue  # It's using a variable, skip
                        
                        issues.append(HardcodedIssue(
                            file_path=str(file_path),
                            line_number=line_num,
                            line_content=line.strip()[:100],
                            hardcoded_value=pattern,
                            expected_config=expected_config,
                            description=description,
                            severity="critical" if "INSERT" in line.upper() or "CREATE" in line.upper() else "warning"
                        ))
                        break  # Only report once per line per pattern
    
    return issues


def run_hardcoded_check(
    root_path: str = ".",
    patterns: Optional[Dict[str, Tuple[str, str]]] = None,
    exclude_dirs: Optional[Set[str]] = None
) -> List[HardcodedIssue]:
    """
    Scan Python files for hardcoded values that should use config.
    
    Args:
        root_path: Root directory to scan
        patterns: Custom patterns dict, or uses HARDCODED_PATTERNS
        exclude_dirs: Directories to exclude (defaults to common exclusions)
    
    Returns:
        List of HardcodedIssue objects
    """
    if patterns is None:
        patterns = HARDCODED_PATTERNS
    
    if exclude_dirs is None:
        exclude_dirs = {"venv", ".venv", "node_modules", "__pycache__", ".git", "tests"}
    
    issues: List[HardcodedIssue] = []
    root = Path(root_path)
    
    # Find all Python files
    py_files = []
    for py_file in root.rglob("*.py"):
        # Skip excluded directories
        if any(excluded in py_file.parts for excluded in exclude_dirs):
            continue
        py_files.append(py_file)
    
    logger.info(f"Scanning {len(py_files)} Python files for hardcoded values...")
    
    for py_file in py_files:
        file_issues = scan_file(py_file, patterns)
        issues.extend(file_issues)
    
    return issues


def print_report(issues: List[HardcodedIssue]) -> None:
    """Print a formatted report of detected issues."""
    print("\n" + "=" * 60)
    print("HARDCODED VALUE DETECTION REPORT")
    print("=" * 60)
    
    if not issues:
        print("\n✅ No hardcoded config values detected!")
        print("=" * 60)
        return
    
    critical_issues = [i for i in issues if i.severity == "critical"]
    warning_issues = [i for i in issues if i.severity == "warning"]
    
    if critical_issues:
        print(f"\n❌ CRITICAL ISSUES ({len(critical_issues)}):")
        print("-" * 40)
        for issue in critical_issues:
            print(f"\n  File: {issue.file_path}:{issue.line_number}")
            print(f"  Hardcoded: '{issue.hardcoded_value}'")
            print(f"  Should use: {issue.expected_config}")
            print(f"  Line: {issue.line_content}")
    
    if warning_issues:
        print(f"\n⚠️  WARNINGS ({len(warning_issues)}):")
        print("-" * 40)
        for issue in warning_issues:
            print(f"\n  File: {issue.file_path}:{issue.line_number}")
            print(f"  Hardcoded: '{issue.hardcoded_value}'")
            print(f"  Should use: {issue.expected_config}")
    
    print("\n" + "=" * 60)
    print(f"Total: {len(critical_issues)} critical, {len(warning_issues)} warnings")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    # Get path from command line or use current directory
    root_path = sys.argv[1] if len(sys.argv) > 1 else "."
    
    issues = run_hardcoded_check(root_path)
    print_report(issues)
    
    # Exit with error code if critical issues found
    critical_count = len([i for i in issues if i.severity == "critical"])
    sys.exit(1 if critical_count > 0 else 0)
