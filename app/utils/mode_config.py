"""
Sage Experimental Mode Configuration

This module provides session-aware mode configuration for switching between
Production and Experimental modes. All environment variables are loaded at
app startup. User mode preferences are stored in Flask sessions.

Usage:
    from mode_config import get_mode, set_mode, get_setting
    
    # Get current user's mode
    current_mode = get_mode()
    
    # Set mode for current user's session
    set_mode('experimental')
    
    # Get a setting based on current mode
    # In experimental mode, checks EXP_KEY first, falls back to KEY
    model = get_setting('AZURE_OPENAI_MODEL')
    
    # For CLI tools outside Flask context, use override:
    from mode_config import set_persona_override, clear_persona_override
    set_persona_override('scientist')
    # ... do work ...
    clear_persona_override()
"""

import logging
import os
from typing import Optional, Any

logger = logging.getLogger(__name__)

# Enhanced self-critique prompt template for structured verification with detailed reasoning
ADVANCED_SELF_CRITIQUE_PROMPT_TEMPLATE = """
# Enhanced Self-Critique with Original Response Preservation

### Task & Persona
You are a meticulous but efficient assistant. You must ALWAYS provide two distinct responses:
1. **Original Response**: Your natural, initial answer based solely on the provided context
2. **Self-Critique Response**: A structured verification and filtering of that original answer

### Selected Policy (provided by system)
{policy_header}

### Source Context
<context>
{context}
</context>

### User Query
{query}

### Step 1: Original Response
First, provide your natural response to the query using only the provided context. This should be your genuine answer as you would normally give it.

### Step 2: Self-Critique Process

#### Inference Policy (catalog of intents)
- Definition/Overview → allow SemanticDirect; forbid new facts
- Conceptual Explanation → allow SemanticDirect; forbid new facts
- How-to/Procedure → Strict Only
- Troubleshooting → Strict Only
- Specs/Numbers/Compliance → Strict Only
- Regulatory/Policy Compliance → Strict Only
- Capabilities/Features → allow SemanticDirect; forbid unlisted features
- Comparisons/Tradeoffs → allow Partial only if all premises sourced; else Speculative or omit
- Recommendations → allow [Speculative] examples; must be labeled; ground any factual claims
- Use cases/Examples → allow [Speculative] examples; must be labeled; ground any factual claims
- Summarization/Paraphrase → allow SemanticDirect; forbid new facts
- Data Extraction/Citation → Strict Only; extract only what is present; include citations
- Risk/Safety → Strict Only; avoid advice beyond sourced content

#### Support Categories
- Direct: explicit or trivial entailment
- SemanticDirect: faithful paraphrase; no new facts
- Partial: mixed; can be rewritten to remove unsupported parts
- Speculative: reasonable, domain-typical example (policy permitting); must be labeled [Speculative]
- Contradicted: sources say the opposite
- NotFound: no support found

#### Verification Requirements
For each sentence in your original response:
- Find the most direct supporting quote(s) from source context
- Provide detailed reasoning for classification
- Assign confidence score (0.0–1.0)
- Identify claim type (factual, statistical, procedural, comparative, causal, example, definitional)
- Suggest alternative phrasing for partial support
- Mark `policy_compliant` true/false

#### Verification budget and prioritization (strict)
- Hard cap: verification_log ≤ 5 items total. If more candidates exist, include only the 5 highest-priority claims below.
- Reasoning length: ≤ 200 characters per item (concise, targeted).
- Quote length: ≤ 180 characters per quote (≤ 2 quotes). Pick the most direct evidence.

Prioritize these claims (in order)
1) Specs/Numbers/Compliance (numerical specs, ranges, percentages, units, regulatory statements)
2) How-to/Procedure steps that could mislead if wrong
3) Risk/Safety / Regulatory assertions (e.g., warnings, compliance constraints)
4) Potentially contradicted or ambiguous claims (low confidence or mixed support)
5) Multi-source synthesis claims (supported by ≥2 sources) or statements anchoring multiple later sentences
6) Comparative/tradeoff or causal claims with meaningful implications
7) Core definitional claims only if central to the user's query (otherwise omit or compress)
8) Trivial restatements and stylistic sentences → omit first when over budget

Selection heuristics (use as tie-breakers)
- +1 if the claim contains numbers or measurement units (°, %, psi, °C, kPa, etc.)
- +1 if supported by multiple source_ids (show them)
- +1 if confidence < 0.90 but still policy-compliant (valuable to inspect)
- +1 if the claim underpins multiple sentences/sections (structural importance)
- −1 if trivial paraphrase or redundant with a higher-priority item
- Prefer coverage across different sections over many items from one paragraph

If over budget
- Keep highest-priority items; drop lowest-priority first (trivial, stylistic).
- Ensure at least one item from any strict category present (Specs/Numbers/Compliance, Procedure, Risk/Safety, Regulatory) if they occur.
- If nothing qualifies beyond definitional claims, include only those that are central to answering the query.

#### Final Answer Rules
- Use only sentences meeting policy requirements and confidence ≥ 0.8
- Apply correct citation [id] format
- Label speculative content as [Speculative] when policy allows
- Use only [n] ids corresponding to the provided <source id="n"> blocks; do not invent other citation numbers.
- Fallback if no reliable content: "I could not find a reliable answer in the provided sources."

#### Length & JSON Constraints (mandatory)
- Output MUST be a single valid JSON object. Do NOT include markdown code fences.
- Escape quotes properly in JSON strings. Avoid unescaped newlines in string values.
- Enforce max lengths:
  - verification_log: ≤ 5 items
  - reasoning ≤ 200 characters per item
  - each quotes[] item ≤ 180 characters
- If limits force truncation, prefer removing lower-confidence items rather than breaking JSON.
- Do not emit raw newlines in any JSON string values; replace newlines with a single space.
- Emit "final_answer" immediately after "draft_answer" and before "verification_log" so that it appears early even if output truncates.
- If you approach the token limit, immediately close and return the JSON object; do not emit partial or unterminated JSON.

### Required Output Format (single JSON object)

{{
  "original_response": "Your complete, natural response to the query based only on the provided context. This is preserved exactly as you would normally answer, without any self-critique applied.",
  "self_critique": {{
    "policy_selected": "The inference policy selected based on query intent",
    "draft_answer": "Reformulated answer during self-critique process (before final filtering)",
    "final_answer": "The verified, policy-compliant answer with proper citations and [Speculative] labels where appropriate",
    "verification_log": [
      {{
        "sentence": "Exact sentence text from original response",
        "status": "Direct | SemanticDirect | Partial | Speculative | Contradicted | NotFound",
        "quotes": ["Most direct supporting quote", "Additional quote if relevant"],
        "source_ids": [1, 2],
        "reasoning": "Detailed explanation of classification, including logical connection between claim and evidence",
        "confidence_score": 0.92,
        "claim_type": "factual | definitional | procedural | statistical | comparative | causal | example",
        "alternative_phrasing": "Conservative rephrasing for partial support (null if not applicable)",
        "policy_compliant": true
      }}
    ],
    "verification_summary": {{
      "policy_selected": "Selected inference policy",
      "totals": {{
        "sentences": 0,
        "direct": 0,
        "semantic_direct": 0,
        "partial": 0,
        "speculative": 0,
        "contradicted": 0,
        "not_found": 0
      }},
      "included": 0,
      "modified": 0,
      "removed": 0,
      "average_confidence": 0.0,
      "policy_violations": 0
    }}
  }}
}}

CRITICAL: The original_response field must ALWAYS contain your complete, initial natural response. Never leave this empty.
"""

# Valid modes and personas
VALID_MODES = ('production', 'experimental')
VALID_PERSONAS = ('explorer', 'intermediate', 'balanced_plus', 'scientist')
VALID_REASONING_EFFORTS = ('low', 'medium', 'high')
VALID_VERBOSITIES = ('low', 'medium', 'high')

# Module-level override for CLI tools running outside Flask context
_persona_override: Optional[str] = None
_mode_override: Optional[str] = None


def set_persona_override(persona: str) -> None:
    """
    Force a specific persona for CLI tools outside Flask context.
    
    Args:
        persona: One of 'explorer', 'intermediate', 'scientist'
    
    Raises:
        ValueError: If persona is not valid
    """
    global _persona_override
    if persona not in VALID_PERSONAS:
        raise ValueError(f"Invalid persona: {persona}. Must be one of {VALID_PERSONAS}")
    _persona_override = persona
    logger.info(f"Persona override set: {persona}")


def clear_persona_override() -> None:
    """Clear the persona override, reverting to session-based or default behavior."""
    global _persona_override
    if _persona_override is not None:
        logger.info(f"Persona override cleared (was: {_persona_override})")
    _persona_override = None


def get_persona_override() -> Optional[str]:
    """Get the current persona override, if any."""
    return _persona_override

# Persona Pipeline Configuration
# Each persona has a specific set of feature flags that control RAG pipeline behavior
PERSONA_CONFIGS = {
    'explorer': {
        # Search configuration - optimized for speed
        'search_top': 50,                       # Return top 50 results from hybrid search
        'search_knn': 50,                    # Use 50 nearest neighbors for vector search
        
        # Pipeline feature flags - minimal processing
        'enable_query_enhancement': False,   # Skip magic wand query enhancement
        'enable_reranker': False,            # Skip LLM-based reranking
        'enable_self_critique': False,       # Skip self-critique validation
        'enable_groundedness_check': False,  # Skip groundedness verification
        'enable_correction_loop': False,     # No correction loop for speed
        'enable_history_summarization': True, # Keep basic summarization
        
        # Context preparation
        'max_context_chunks': 3,             # Use fewer chunks for faster response
        
        # Response settings
        'max_tokens': 800,                   # Shorter responses
        'temperature': 0.3,                  # More focused responses
        
        # GPT-5 Responses API Configuration (requires api_version 2025-03-01-preview)
        'use_responses_api': True,           # Use Responses API instead of Chat Completions
        'responses_api_version': '2025-03-01-preview',  # API version for Responses API
        'reasoning_effort': 'low',           # Quick, direct answers
        'verbosity': 'low',                  # Concise responses
        
        # Verification policy settings
        'verification_policies': {
            'allow_paraphrasing_at_confidence': 0.85,
            'allow_semantic_direct': True,
            'allow_speculative_examples': True,
            'strict_only_mode': False,
        },
        
        # Description
        'description': 'Fast pipeline for quick exploratory questions'
    },
    
    'intermediate': {
        # Search configuration - balanced
        'search_top': 30,                    # Return top 30 results
        'search_knn': 30,                    # Use 30 nearest neighbors
        
        # Pipeline feature flags - selective processing
        'enable_query_enhancement': True,    # Use query enhancement
        'enable_reranker': True,             # Apply reranking for better relevance
        'enable_self_critique': True,        # Basic quality validation
        'async_self_critique': True,         # Run self-critique async (doesn't block response)
        'enable_groundedness_check': False,  # Skip expensive groundedness check
        'enable_correction_loop': False,     # No correction loop for balanced speed
        'enable_history_summarization': True,
        
        # Context preparation
        'max_context_chunks': 5,             # Standard chunk count
        
        # Response settings
        'max_tokens': 1200,                  # Moderate response length
        'temperature': 0.5,                  # Balanced creativity
        
        # GPT-5 Responses API Configuration (requires api_version 2025-03-01-preview)
        'use_responses_api': True,           # Use Responses API instead of Chat Completions
        'responses_api_version': '2025-03-01-preview',  # API version for Responses API
        'reasoning_effort': 'medium',        # Balanced analysis
        'verbosity': 'medium',               # Balanced detail
        
        # Verification policy settings
        'verification_policies': {
            'allow_paraphrasing_at_confidence': 0.90,
            'allow_semantic_direct': True,
            'allow_speculative_examples': False,
            'strict_only_mode': False,
        },
        
        # Self-critique policy for balanced mode
        'self_critique_policy': 'Balanced Mode: Allow semantic paraphrasing and direct entailment. Forbid speculative examples. Require confidence ≥ 0.90 for paraphrasing.',
        
        # Description
        'description': 'Balanced pipeline with query enhancement and reranking',

        # System Prompt Configuration for Balanced Mode
        'system_prompt_mode': 'Override',
        'system_prompt': """
adopt the role of a Helpful & Accurate Enterprise Assistant.

### Reasoning Process (Context Prompting):
1. **Analyze**: Understand the user's core question and intent.
2. **Retrieve**: Look for direct answers in the provided <source> tags.
3. **Synthesize**: Combine information to provide a complete answer.
4. **Verify**: Ensure every claim is backed by a citation [id].

### RADAR Quality Standards:
- **Resolution**: Answer the question directly.
- **Tone**: Be professional, confident, but grounded (avoid overclaiming).
- **Format**: Use clear headings and bullet points for readability.

### Guidelines:
- If you don't know the answer, clearly state that.
- If uncertain, ask the user for clarification.
- Respond in the same language as the user's query.
- If the context is unreadable or of poor quality, inform the user and provide the best possible answer.
- Maintain continuity with previous conversation by referencing earlier exchanges when appropriate.

### Citation Requirements (MANDATORY):
- Incorporate inline citations in the format [id] **only when the <source> tag includes an explicit id attribute** (e.g., <source id="1">).
- Do not cite if the <source> tag does not contain an id attribute.
- Do not use XML tags in your response.
- Ensure citations are concise and directly related to the information provided.
- **Always cite your sources in every response, including follow-up questions.**
- Citations are mandatory ONLY for information strictly derived from the context.
- If the context does not contain the answer, state that you cannot find the information in the provided sources. DO NOT fabricate a citation.

### Example of Citation:

* "According to the documentation, the proposed method increases efficiency by 20% [1]."

### Follow-up Questions:

User: "What are the key features of Product X?"
Assistant: "Product X has three main features: cloud integration [1], advanced analytics [2], and mobile support [3]."

User: "Tell me more about the mobile support."
Assistant: "The mobile support feature of Product X includes cross-platform compatibility, offline mode, and push notifications [3]."
        """,

        # RADAR Correction Loop Configuration (Evaluate Only for Balanced)
        'enable_radar_correction': True,
        'radar_correction_temperature': 0.5,
        'radar_correction_max_rounds': 1,
        'radar_correction_thresholds': {
            'query_resolution': 0.60,  # Lenient
            'scope_discipline': 0.60,
            'completeness': 0.60,
            'clarity': 0.60,
            'actionability': 0.50,
            'citation_hygiene': 0.70,
        },
        'self_correct_mode': 'evaluate_only'  # Log quality but don't add latency
    },
    
    'balanced_plus': {
        # Search configuration - enhanced balanced (between intermediate and scientist)
        'search_top': 50,                    # More results than intermediate (30), fewer than scientist (100)
        'search_knn': 40,                    # More neighbors than intermediate (30)
        
        # Pipeline feature flags - selective metacognition
        'enable_query_enhancement': True,    # Use query enhancement
        'enable_reranker': True,             # Apply reranking for better relevance
        'enable_self_critique': True,        # Keep self-critique as verification safety net
        'async_self_critique': True,         # Run self-critique async (doesn't block response)
        'enable_groundedness_check': False,  # Skip expensive groundedness check
        'enable_correction_loop': False,     # No correction loop — prompt does the heavy lifting
        'enable_history_summarization': True,
        
        # Context preparation
        'max_context_chunks': 7,             # More context than intermediate (5), less than scientist (10)
        
        # Response settings
        'max_tokens': 1500,                  # Between intermediate (1200) and scientist (2000)
        'temperature': 0.5,                  # Same as intermediate — keep balanced creativity
        
        # GPT-5 Responses API Configuration (requires api_version 2025-03-01-preview)
        'use_responses_api': True,           # Use Responses API instead of Chat Completions
        'responses_api_version': '2025-03-01-preview',  # API version for Responses API
        'reasoning_effort': 'medium',        # Keep medium — the prompt strategy compensates
        'verbosity': 'medium',               # Balanced detail
        
        # System Prompt Configuration — SELECTIVE METACOGNITION
        # Transplants Decompose + Synthesize from Scientist without Verify/Reflect overhead
        'system_prompt_mode': 'Override',
        'system_prompt': """
You are a precise and reliable technical assistant.

Before responding:
1. **Understand Intent**: Identify what the user is actually asking — the core question and any implicit sub-questions.
2. **Assess Coverage**: Determine which parts of the question the provided context can answer, and which it cannot.
3. **Calibrate Certainty**: For each claim you make, match your language to your evidence strength:
   - Strong source support → state directly
   - Partial support → use "Based on the documentation..." or "Typically..."
   - No support → explicitly state the limitation rather than guessing

Respond with:
- A direct answer to the core question first
- Supporting details organized logically
- Honest acknowledgment of what the sources don't cover

### Citation Requirements (MANDATORY):
- Evaluate the provided context and incorporate inline citations in the format [id] **only when the <source> tag includes an explicit id attribute** (e.g., <source id="1">).
- **Only include inline citations using [id] (e.g., [1], [2]) when the <source> tag includes an id attribute.**
- Do not cite if the <source> tag does not contain an id attribute.
- Ensure citations are concise and directly related to the information provided.
- **IMPORTANT: For follow-up questions, continue to use citations [id] when referencing information from the provided context.**

Do NOT pad your response with unnecessary caveats or disclaimers to appear cautious. Be concise and useful.
        """,
        
        # Verification policy settings — same as intermediate but tighter paraphrasing
        'verification_policies': {
            'allow_paraphrasing_at_confidence': 0.90,
            'allow_semantic_direct': True,
            'allow_speculative_examples': False,
            'strict_only_mode': False,
        },
        
        # Self-critique policy
        'self_critique_policy': 'Balanced Plus Mode: Selective metacognition with intent decomposition and evidence calibration. Allow semantic paraphrasing and direct entailment. Forbid speculative examples. Require confidence >= 0.90 for paraphrasing.',
        
        # RADAR Correction Loop Configuration (Evaluate Only — same as Balanced)
        'enable_radar_correction': True,
        'radar_correction_temperature': 0.5,
        'radar_correction_max_rounds': 1,
        'radar_correction_thresholds': {
            'query_resolution': 0.65,
            'scope_discipline': 0.65,
            'completeness': 0.65,
            'clarity': 0.60,
            'actionability': 0.55,
            'citation_hygiene': 0.75,
        },
        'self_correct_mode': 'evaluate_only',  # Log quality but don't add latency
        
        # Description
        'description': 'Enhanced balanced pipeline with selective metacognition system prompt — decomposition and synthesis without full RADAR correction overhead'
    },
    
    'scientist': {
        # Search configuration - comprehensive
        'search_top': 100,                    # Return top 100 results (quality over quantity)
        'search_knn': 50,                    # Use 50 nearest neighbors
        
        # Pipeline feature flags - full processing
        'enable_query_enhancement': True,    # Use query enhancement
        'enable_reranker': True,             # Apply reranking
        'enable_self_critique': False,       # Skip self-critique validation (rely on correction loop + final check)
        'enable_groundedness_check': True,   # Verify groundedness
        'enable_correction_loop': True,      # Apply corrections before final response
        'correction_threshold': 0.75,        # Correct if score < 0.75
        'max_correction_rounds': 1,          # Single correction pass
        'enable_history_summarization': True,
        
        # Context preparation
        'max_context_chunks': 10,             # Full context
        
        # Response settings
        'max_tokens': 2000,                  # Detailed responses
        'temperature': 0.7,                  # More nuanced responses
        
        # GPT-5 Responses API Configuration (requires api_version 2025-03-01-preview)
        'use_responses_api': True,           # Use Responses API instead of Chat Completions
        'responses_api_version': '2025-03-01-preview',  # API version for Responses API
        'reasoning_effort': 'high',          # Deep step-by-step reasoning
        'verbosity': 'high',                 # Comprehensive, detailed responses
        
        # System Prompt Configuration
        'system_prompt_mode': 'Override',    # Complete control over prompt
        'system_prompt': """
adopt the role of a Meta-Cognitive Reasoning Expert.

For every complex problem:
1. Decompose: Break into sub-problems
2. Solve: Address each with explicit confidence (0.0 - 1.0)
3. Verify: Check logic, facts, completeness, bias
4. Synthesize: Combine using weighted confidence
5. Reflect: If confidence <0.8, identify weakness and retry

For simple questions, skip to direct answer.

### Citation Requirements (MANDATORY):
- Evaluate the provided context and incorporate inline citations in the format [id] **only when the <source> tag includes an explicit id attribute** (e.g., <source id="1">).
- **Only include inline citations using [id] (e.g., [1], [2]) when the <source> tag includes an id attribute.**
- Do not cite if the <source> tag does not contain an id attribute.
- Ensure citations are concise and directly related to the information provided.
- **IMPORTANT: For follow-up questions, continue to use citations [id] when referencing information from the provided context.**


Always output:
Clear answer
Key caveats
        """,
        
        # Verification policy settings - STRICT mode for maximum fidelity
        'verification_policies': {
            'allow_paraphrasing_at_confidence': None,  # Never allow paraphrasing
            'allow_semantic_direct': False,
            'allow_speculative_examples': False,
            'strict_only_mode': True,  # Maximum fidelity mode
        },
        
        # Self-critique policy for scientist mode
        'self_critique_policy': 'Strict Mode: Only direct citations allowed. No paraphrasing, no semantic inference, no speculative examples. Maximum fidelity to source material.',

        # RADAR Correction Loop Configuration (replaces binary groundedness correction)
        # Multi-dimensional quality improvement with engagement preservation
        'enable_radar_correction': True,  # Use RADAR instead of binary groundedness
        'radar_correction_temperature': 0.6,  # Higher temp for natural flow (vs 0.3 in old loop)
        'radar_correction_max_rounds': 1,  # Single correction pass
        'radar_correction_thresholds': {
            'query_resolution': 0.70,  # Intent must be satisfied
            'scope_discipline': 0.70,  # No overclaiming / overconfidence
            'completeness': 0.70,  # Must cover key aspects
            'clarity': 0.60,  # Lower bar for readability
            'actionability': 0.65,  # Nice to have concrete steps
            'citation_hygiene': 0.80,  # Citation formatting only
        },
        # RADAR self-correction mode: 'true' | 'evaluate_only' | 'false'
        'self_correct_mode': 'true',  # true=correct, evaluate_only=log only, false=skip

        # Description
        'description': 'Full pipeline with all verification and quality checks'
    }
}

# Cache for experimental settings detected at startup
_experimental_settings_cache = None


def _discover_experimental_settings() -> set:
    """
    Discover all EXP_ prefixed environment variables at startup.
    Returns a set of base key names that have experimental overrides.
    """
    global _experimental_settings_cache
    if _experimental_settings_cache is None:
        _experimental_settings_cache = set()
        for key in os.environ:
            if key.startswith('EXP_'):
                base_key = key[4:]  # Remove 'EXP_' prefix
                _experimental_settings_cache.add(base_key)
        logger.info(f"Discovered {len(_experimental_settings_cache)} experimental settings")
    return _experimental_settings_cache


def get_mode() -> str:
    """
    Get the current user's mode from their Flask session.
    Returns 'production' if no mode is set or if outside request context.
    """
    try:
        from flask import session
        return session.get('sage_mode', 'experimental')
    except RuntimeError:
        # Outside of request context
        return 'experimental'


def set_mode(mode: str) -> bool:
    """
    Set the mode for the current user's session.
    
    Args:
        mode: Either 'production' or 'experimental'
        
    Returns:
        True if mode was set successfully, False otherwise
    """
    if mode not in VALID_MODES:
        logger.warning(f"Invalid mode '{mode}', must be one of {VALID_MODES}")
        return False
    
    try:
        from flask import session
        old_mode = session.get('sage_mode', 'production')
        session['sage_mode'] = mode
        logger.info(f"Mode changed: {old_mode} -> {mode}")
        return True
    except RuntimeError:
        logger.error("Cannot set mode outside of request context")
        return False


def get_persona() -> Optional[str]:
    """
    Get the current user's persona.
    
    Priority order:
    1. Module-level override (for CLI tools outside Flask context)
    2. Flask session value
    3. Default: None (production mode - no persona-based overrides)
    """
    # Check for CLI override first
    if _persona_override is not None:
        return _persona_override
    
    try:
        from flask import session
        return session.get('sage_persona', 'intermediate')
    except RuntimeError:
        # Outside of request context
        return None


def set_persona(persona: str) -> bool:
    """
    Set the persona for the current user's session.
    
    Args:
        persona: One of ('explorer', 'intermediate', 'scientist')
        
    Returns:
        True if persona was set successfully, False otherwise
    """
    if persona not in VALID_PERSONAS:
        logger.warning(f"Invalid persona '{persona}', must be one of {VALID_PERSONAS}")
        return False
    
    try:
        from flask import session
        old_persona = session.get('sage_persona', 'explorer')
        session['sage_persona'] = persona
        logger.info(f"Persona changed: {old_persona} -> {persona}")
        return True
    except RuntimeError:
        logger.error("Cannot set persona outside of request context")
        return False


def set_reasoning_effort(value: str) -> bool:
    """
    Set the reasoning effort override for the current user's session.
    When set, this overrides the persona's default reasoning_effort.

    Args:
        value: One of ('low', 'medium', 'high')

    Returns:
        True if set successfully, False otherwise
    """
    if value not in VALID_REASONING_EFFORTS:
        logger.warning(f"Invalid reasoning_effort '{value}', must be one of {VALID_REASONING_EFFORTS}")
        return False

    try:
        from flask import session
        old = session.get('sage_reasoning_effort')
        session['sage_reasoning_effort'] = value
        logger.info(f"Reasoning effort override changed: {old} -> {value}")
        return True
    except RuntimeError:
        logger.error("Cannot set reasoning_effort outside of request context")
        return False


def get_reasoning_effort() -> Optional[str]:
    """Get the user's reasoning effort override from session, or None if not set."""
    try:
        from flask import session
        return session.get('sage_reasoning_effort')
    except RuntimeError:
        return None


def set_verbosity(value: str) -> bool:
    """
    Set the verbosity override for the current user's session.
    When set, this overrides the persona's default verbosity.

    Args:
        value: One of ('low', 'medium', 'high')

    Returns:
        True if set successfully, False otherwise
    """
    if value not in VALID_VERBOSITIES:
        logger.warning(f"Invalid verbosity '{value}', must be one of {VALID_VERBOSITIES}")
        return False

    try:
        from flask import session
        old = session.get('sage_verbosity')
        session['sage_verbosity'] = value
        logger.info(f"Verbosity override changed: {old} -> {value}")
        return True
    except RuntimeError:
        logger.error("Cannot set verbosity outside of request context")
        return False


def get_verbosity() -> Optional[str]:
    """Get the user's verbosity override from session, or None if not set."""
    try:
        from flask import session
        return session.get('sage_verbosity')
    except RuntimeError:
        return None


def get_persona_config(current_persona=None) -> dict:
    """
    Get the complete pipeline configuration for the current persona.
    
    Returns:
        Dictionary with all feature flags and settings for the current persona,
        or empty dict if persona is None (production mode)
    """
    if not current_persona:
        current_persona = get_persona()
    
    # If persona is None (production mode), return empty config
    # This allows environment-based defaults to take precedence
    if current_persona is None:
        logger.debug("No persona set - using environment-based defaults (production mode)")
        return {}
    
    config = PERSONA_CONFIGS.get(current_persona, {})
    logger.debug(f"Retrieved config for persona '{current_persona}': {config.get('description', 'N/A')}")
    return config


def get_setting_of_persona(key: str, default: Optional[Any] = None, persona=None) -> Any:
    """
    Get a specific setting value from the current persona's configuration.
    
    Args:
        key: The setting key (e.g., 'search_top', 'enable_reranker')
        default: Default value if key not found
        
    Returns:
        The setting value for the current persona, or default if not found
    """
    config = get_persona_config(current_persona=persona)
    value = config.get(key, default)
    if value is None:
        value = get_setting(key, default)
    logger.debug(f"Persona setting '{key}' = {value} (persona: {persona})")
    return value


def get_setting(key: str, default: Optional[Any] = None) -> Optional[str]:
    """
    Get a setting value based on the current user's mode.
    
    In experimental mode:
      - First checks for EXP_{key} environment variable
      - Falls back to {key} if EXP_ version doesn't exist
      
    In production mode:
      - Uses {key} directly
      
    Args:
        key: The base environment variable name (without EXP_ prefix)
        default: Default value if key not found
        
    Returns:
        The setting value as a string, or default if not found
    """
    mode = get_mode()
    
    if mode == 'experimental':
        exp_key = f"EXP_{key}"
        exp_value = os.getenv(exp_key)
        if exp_value is not None:
            logger.debug(f"Using experimental value for {key}")
            return exp_value
    
    return os.getenv(key, default)


def get_setting_bool(key: str, default: bool = False) -> bool:
    """
    Get a boolean setting value based on current mode.
    
    Interprets 'true', '1', 'yes' as True (case-insensitive).
    """
    value = get_setting(key)
    if value is None:
        return default
    return value.lower() in ('true', '1', 'yes', 'on')


def get_setting_int(key: str, default: int = 0) -> int:
    """Get an integer setting value based on current mode."""
    value = get_setting(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(f"Invalid integer value for {key}: {value}")
        return default


def get_setting_float(key: str, default: float = 0.0) -> float:
    """Get a float setting value based on current mode."""
    value = get_setting(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning(f"Invalid float value for {key}: {value}")
        return default


def get_mode_info() -> dict:
    """
    Get comprehensive information about current mode and available features.
    Useful for debugging and API responses.
    """
    mode = get_mode()
    persona = get_persona()
    experimental_keys = _discover_experimental_settings()
    
    return {
        'mode': mode,
        'persona': persona,
        'reasoning_effort': get_reasoning_effort(),
        'verbosity': get_verbosity(),
        'is_experimental': mode == 'experimental',
        'available_experimental_overrides': len(experimental_keys),
        'features': {
            'model': get_setting_of_persona('AZURE_OPENAI_MODEL',persona=persona),
            'reranker_enabled': get_setting_of_persona('enable_reranker', persona=persona),
            'groundedness_enabled': get_setting_of_persona('enable_groundedness_check', persona=persona),
            'self_critique_enabled': get_setting_of_persona('enable_self_critique', persona=persona),
            'self_judge_enabled': get_setting_bool('ENABLE_SELF_JUDGE'),
        }
    }


# Initialize cache on module load
_discover_experimental_settings()
