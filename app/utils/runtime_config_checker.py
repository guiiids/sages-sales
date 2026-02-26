"""
Runtime Config Checker

Runs at startup to detect config drift between environment variables,
.env.example declarations, and actual resolved runtime values.

Usage:
    from utils.runtime_config_checker import run_config_check
    from utils.config_resolver import get_resolver
    
    # After config resolution is complete:
    run_config_check(get_resolver())
"""

import os
import logging
from pathlib import Path
from typing import Dict, Set, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConfigIssue:
    """Represents a detected config issue."""
    severity: str  # "warning" or "critical"
    issue_type: str  # "drift", "multi_source", "unused_env"
    key: str
    message: str
    details: Optional[str] = None


def parse_env_example(env_example_path: str = ".env.example") -> Dict[str, str]:
    """
    Parse .env.example to get declared variable names and their example values.
    
    Returns dict of {VAR_NAME: example_value}
    """
    declared_vars: Dict[str, str] = {}
    
    path = Path(env_example_path)
    if not path.exists():
        logger.warning(f".env.example not found at {env_example_path}")
        return declared_vars
    
    try:
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            
            # Skip comments and empty lines
            if not stripped or stripped.startswith("#"):
                continue
            
            # Parse VAR=value
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                value = stripped.split("=", 1)[1].strip() if "=" in stripped else ""
                if key and key[0].isupper():
                    declared_vars[key] = value
    except Exception as e:
        logger.error(f"Failed to parse .env.example: {e}")
    
    return declared_vars


def run_config_check(
    resolver,
    env_example_path: str = ".env.example",
    strict: bool = None
) -> List[ConfigIssue]:
    """
    Run runtime config checks and emit warnings.
    
    Args:
        resolver: ConfigResolver instance with recorded resolutions
        env_example_path: Path to .env.example file
        strict: If True, raise SystemExit on critical issues.
                If None, reads from CONFIG_CHECK_STRICT env var.
    
    Returns:
        List of detected ConfigIssue objects
    """
    if strict is None:
        strict = os.environ.get("CONFIG_CHECK_STRICT", "false").lower() == "true"
    
    issues: List[ConfigIssue] = []
    resolutions = resolver.get_resolutions()
    declared_vars = parse_env_example(env_example_path)
    
    logger.info("=" * 50)
    logger.info("=== Runtime Config Check ===")
    
    # Check 1: Multi-source conflicts
    conflicts = resolver.get_conflicts()
    if conflicts:
        logger.warning(f"Found {len(conflicts)} config(s) with multi-source resolution")
        for key, record in conflicts.items():
            sources_detail = []
            for source_name, value, was_winner in record.attempted_sources:
                marker = "→" if was_winner else " "
                sources_detail.append(f"    {marker} {source_name} = {value!r}")
            
            detail = "\n".join(sources_detail)
            issue = ConfigIssue(
                severity="warning",
                issue_type="multi_source",
                key=key,
                message=f"{key} resolved from multiple sources",
                details=f"Winner: {record.final_value!r}\n{detail}"
            )
            issues.append(issue)
            
            logger.warning(f"⚠️  MULTI-SOURCE: {key}")
            logger.warning(f"   Winner: {record.final_value!r} ({record.winning_source})")
            for line in sources_detail:
                logger.warning(line)
    
    # Check 2: Env var set but overridden
    for key, record in resolutions.items():
        if "override:" in record.winning_source:
            # Check if there was an env value that got overridden
            for source_name, value, was_winner in record.attempted_sources:
                if source_name.startswith("env:") and value is not None and not was_winner:
                    issue = ConfigIssue(
                        severity="critical" if strict else "warning",
                        issue_type="drift",
                        key=key,
                        message=f"{key} is set to {value!r} in env but overridden to {record.final_value!r}",
                        details=f"Source: {record.winning_source}"
                    )
                    issues.append(issue)
                    
                    logger.warning(f"⚠️  CONFIG DRIFT: {key}")
                    logger.warning(f"   Env value: {value!r} (ignored)")
                    logger.warning(f"   Runtime value: {record.final_value!r}")
                    logger.warning(f"   Override: {record.winning_source}")
    
    # Check 3: Env vars set but not tracked
    # (Only if we have tracked any resolutions - otherwise this is a no-op)
    untracked_vars = []
    if resolutions:
        tracked_env_keys: Set[str] = set()
        for record in resolutions.values():
            for source_name, _, _ in record.attempted_sources:
                if source_name.startswith("env:"):
                    tracked_env_keys.add(source_name.split(":", 1)[1])
        
        # Find env vars that look like config but weren't tracked
        for env_key in os.environ:
            # Skip system/shell vars
            if not env_key[0].isupper() or env_key.startswith(("_", "PATH", "HOME", "USER", "SHELL", "TERM", "LANG", "LC_")):
                continue
            
            # If it's in .env.example but not tracked, it might be unused
            if env_key in declared_vars and env_key not in tracked_env_keys:
                # Only warn if it looks like our app's config
                if any(prefix in env_key for prefix in ["AZURE", "OPENAI", "SEARCH", "COSMOS", "POSTGRES", "REDIS", "ENABLE_", "RERANKER", "COHERE"]):
                    issue = ConfigIssue(
                        severity="warning",
                        issue_type="unused_env",
                        key=env_key,
                        message=f"{env_key} is set in env but not tracked by resolver",
                        details="This var may not be instrumented yet"
                    )
                    issues.append(issue)
                    untracked_vars.append(env_key)
        
        # Log untracked vars with a clear header
        if untracked_vars:
            logger.info(f"--- Untracked Env Vars ({len(untracked_vars)}) ---")
            logger.info("   (Set in env + declared in .env.example, but not instrumented)")
            for var in sorted(untracked_vars):
                logger.info(f"   • {var}")
    
    # Summary
    critical_count = len([i for i in issues if i.severity == "critical"])
    warning_count = len([i for i in issues if i.severity == "warning"])
    
    if issues:
        logger.warning("-" * 50)
        if critical_count > 0:
            logger.warning(f"❌ {critical_count} critical issue(s)")
        if warning_count > 0:
            logger.warning(f"⚠️  {warning_count} warning(s)")
    else:
        logger.info("✅ No config drift detected")
    
    logger.info("=" * 50)
    
    # Strict mode: fail on critical issues
    if strict and critical_count > 0:
        logger.error("CONFIG_CHECK_STRICT=true: Failing startup due to critical config issues")
        raise SystemExit(1)
    
    return issues


def log_config_summary(resolver) -> None:
    """Log a summary of resolved config values, masking sensitive keys."""
    resolutions = resolver.get_resolutions()
    
    # Keys that should be masked (contain secrets)
    SENSITIVE_PATTERNS = ('KEY', 'SECRET', 'PASSWORD', 'TOKEN', 'CREDENTIAL', 'API_KEY')
    
    def mask_value(key: str, value) -> str:
        """Mask sensitive values, showing only first/last 4 chars."""
        if any(pattern in key.upper() for pattern in SENSITIVE_PATTERNS):
            if value and len(str(value)) > 8:
                v = str(value)
                return f"{v[:4]}...{v[-4:]}"
            return "****"
        return repr(value)
    
    logger.info("=== Resolved Config Summary ===")
    for key, record in sorted(resolutions.items()):
        conflict_marker = " [!]" if record.had_conflict() else ""
        masked_value = mask_value(key, record.final_value)
        logger.info(f"  {key}: {masked_value} ({record.winning_source}){conflict_marker}")

