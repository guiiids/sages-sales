"""
Instrumented Config Resolver

Wraps os.getenv to track config resolution sources for runtime diagnostics.
Each resolved value records where it came from (env var, fallback, default, override).

Usage:
    from utils.config_resolver import ConfigResolver
    
    resolver = ConfigResolver()
    value, source = resolver.get("CHAT_DEPLOYMENT", default="gpt-4o", fallback_keys=["AZURE_OPENAI_MODEL"])
    # value = "gpt-4o-prod"
    # source = "env:AZURE_OPENAI_MODEL"
"""

import os
import logging
from typing import Any, Optional, List, Tuple, Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ResolutionRecord:
    """Records a single config resolution with all attempted sources."""
    key: str
    final_value: Any
    winning_source: str
    attempted_sources: List[Tuple[str, Any, bool]] = field(default_factory=list)
    # Each tuple: (source_name, value_found, was_winner)
    
    def had_conflict(self) -> bool:
        """Returns True if multiple sources had values."""
        non_empty_sources = [s for s in self.attempted_sources if s[1] is not None]
        return len(non_empty_sources) > 1


class ConfigResolver:
    """
    Instrumented config resolver that tracks value sources.
    
    After resolution, use get_resolution_report() to see all config paths.
    """
    
    def __init__(self):
        self._resolutions: Dict[str, ResolutionRecord] = {}
    
    def get(
        self,
        key: str,
        default: Any = None,
        fallback_keys: Optional[List[str]] = None,
    ) -> Tuple[Any, str]:
        """
        Resolve a config value with source tracking.
        
        Args:
            key: Primary environment variable name
            default: Default value if no env var found
            fallback_keys: Alternative env var names to try (in order)
        
        Returns:
            Tuple of (resolved_value, source_description)
        """
        fallback_keys = fallback_keys or []
        attempted: List[Tuple[str, Any, bool]] = []
        
        # Try primary key
        primary_value = os.environ.get(key)
        attempted.append((f"env:{key}", primary_value, False))
        
        if primary_value is not None:
            source = f"env:{key}"
            record = ResolutionRecord(
                key=key,
                final_value=primary_value,
                winning_source=source,
                attempted_sources=[(f"env:{key}", primary_value, True)]
            )
            self._resolutions[key] = record
            return primary_value, source
        
        # Try fallback keys
        for fallback_key in fallback_keys:
            fallback_value = os.environ.get(fallback_key)
            is_winner = fallback_value is not None and all(
                s[1] is None for s in attempted
            )
            attempted.append((f"env:{fallback_key}", fallback_value, is_winner))
            
            if fallback_value is not None:
                source = f"fallback:{fallback_key}"
                # Mark winner
                attempted[-1] = (f"env:{fallback_key}", fallback_value, True)
                record = ResolutionRecord(
                    key=key,
                    final_value=fallback_value,
                    winning_source=source,
                    attempted_sources=attempted
                )
                self._resolutions[key] = record
                return fallback_value, source
        
        # Fall back to default
        source = "default"
        attempted.append(("default", default, True))
        record = ResolutionRecord(
            key=key,
            final_value=default,
            winning_source=source,
            attempted_sources=attempted
        )
        self._resolutions[key] = record
        return default, source
    
    def register_override(
        self,
        key: str,
        override_value: Any,
        override_source: str,
        original_value: Any = None,
        original_source: str = None
    ) -> None:
        """
        Register a hardcoded override that supersedes env resolution.
        
        Use this when code explicitly overrides a resolved value.
        
        Args:
            key: Config key being overridden
            override_value: The hardcoded value
            override_source: Description of where override happens (e.g., "rag_assistant.py:184")
            original_value: The value that was overridden (if known)
            original_source: Source of original value (if known)
        """
        attempted = []
        if original_value is not None:
            attempted.append((original_source or "resolved", original_value, False))
        attempted.append((f"override:{override_source}", override_value, True))
        
        record = ResolutionRecord(
            key=key,
            final_value=override_value,
            winning_source=f"override:{override_source}",
            attempted_sources=attempted
        )
        self._resolutions[key] = record
    
    def get_resolutions(self) -> Dict[str, ResolutionRecord]:
        """Return all recorded resolutions."""
        return self._resolutions.copy()
    
    def get_conflicts(self) -> Dict[str, ResolutionRecord]:
        """Return only resolutions where multiple sources had values."""
        return {k: v for k, v in self._resolutions.items() if v.had_conflict()}
    
    def format_resolution_report(self) -> str:
        """Generate a human-readable report of all resolutions."""
        lines = ["=== Config Resolution Report ==="]
        
        for key, record in sorted(self._resolutions.items()):
            conflict_marker = " ⚠️ CONFLICT" if record.had_conflict() else ""
            lines.append(f"\n{key}{conflict_marker}")
            lines.append(f"  Final: {record.final_value!r}")
            lines.append(f"  Source: {record.winning_source}")
            
            if record.had_conflict():
                lines.append("  All sources:")
                for source_name, value, was_winner in record.attempted_sources:
                    marker = "→" if was_winner else " "
                    lines.append(f"    {marker} {source_name} = {value!r}")
        
        return "\n".join(lines)


# Global resolver instance for convenience
_global_resolver: Optional[ConfigResolver] = None


def get_resolver() -> ConfigResolver:
    """Get or create the global ConfigResolver instance."""
    global _global_resolver
    if _global_resolver is None:
        _global_resolver = ConfigResolver()
    return _global_resolver


def resolve_config(
    key: str,
    default: Any = None,
    fallback_keys: Optional[List[str]] = None
) -> Tuple[Any, str]:
    """
    Convenience function to resolve config using the global resolver.
    
    Returns (value, source) tuple.
    """
    return get_resolver().get(key, default=default, fallback_keys=fallback_keys)


def register_override(
    key: str,
    override_value: Any,
    override_source: str,
    original_value: Any = None,
    original_source: str = None
) -> None:
    """Convenience function to register an override using the global resolver."""
    get_resolver().register_override(
        key, override_value, override_source, original_value, original_source
    )
