"""
Language detection utilities for RAG evaluation.

Provides helpers to detect query language and adjust evaluation behavior
for non-English queries where standard metrics may not apply directly.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy load langdetect to avoid import overhead when not needed
_langdetect_available: Optional[bool] = None


def _ensure_langdetect():
    """Lazily import and verify langdetect availability."""
    global _langdetect_available
    if _langdetect_available is None:
        try:
            from langdetect import detect, DetectorFactory
            # Set seed for consistent results
            DetectorFactory.seed = 0
            _langdetect_available = True
        except ImportError:
            logger.warning("langdetect not installed. Language detection disabled. Install with: pip install langdetect")
            _langdetect_available = False
    return _langdetect_available


def detect_language(text: str) -> str:
    """
    Detect the primary language of the given text.
    
    Args:
        text: The text to analyze
        
    Returns:
        ISO 639-1 language code (e.g., 'en', 'zh-cn', 'es', 'ja')
        Returns 'unknown' if detection fails or langdetect is not available.
    """
    if not text or len(text.strip()) < 3:
        return 'unknown'
    
    if not _ensure_langdetect():
        return 'unknown'
    
    try:
        from langdetect import detect
        return detect(text)
    except Exception as e:
        logger.debug(f"Language detection failed for text: {text[:50]}... Error: {e}")
        return 'unknown'


def is_non_english(text: str) -> bool:
    """
    Quick check if text is likely not in English.
    
    Args:
        text: The text to check
        
    Returns:
        True if the text appears to be non-English, False otherwise.
        Returns False if detection is unavailable (assumes English).
    """
    lang = detect_language(text)
    return lang not in ('en', 'unknown')


def get_language_name(code: str) -> str:
    """
    Get human-readable language name from ISO 639-1 code.
    
    Args:
        code: ISO 639-1 language code
        
    Returns:
        Human-readable language name
    """
    LANGUAGE_NAMES = {
        'en': 'English',
        'zh-cn': 'Chinese (Simplified)',
        'zh-tw': 'Chinese (Traditional)',
        'ja': 'Japanese',
        'ko': 'Korean',
        'es': 'Spanish',
        'fr': 'French',
        'de': 'German',
        'pt': 'Portuguese',
        'ru': 'Russian',
        'ar': 'Arabic',
        'hi': 'Hindi',
        'it': 'Italian',
        'nl': 'Dutch',
        'pl': 'Polish',
        'tr': 'Turkish',
        'vi': 'Vietnamese',
        'th': 'Thai',
        'unknown': 'Unknown',
    }
    return LANGUAGE_NAMES.get(code, code.upper())
