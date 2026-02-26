"""
Verification Policy Engine

Defines policies that control groundedness evaluation behavior based on
confidence thresholds, intent classification, and answer characteristics.

Example Policy (PARAPHRASING_ALLOWED):
    If citation confidence >= 90%, allow semantically equivalent statements
    that don't use exact source wording.

Inspired by self_judge.py verification metadata architecture with:
- Policy selection based on confidence/grounding ratios
- Persona-aware strictness levels
- Comprehensive metadata for debugging and observability
"""

import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class VerificationPolicy:
    """
    A single verification policy with trigger conditions and effects.
    
    Attributes:
        name: Unique identifier for the policy
        description: Human-readable description
        enabled: Whether this policy is active
        min_confidence: Minimum average confidence to trigger this policy
        max_confidence: Maximum average confidence for this policy
        min_grounded_ratio: Minimum ratio of supported claims
        allow_paraphrasing: Accept semantic equivalents (not exact wording)
        allow_implicit_inference: Accept logical inferences from sources
        require_direct_citation: Require explicit [n] citations
        strict_claim_matching: Use exact vs semantic claim matching
        priority: Higher priority policies are evaluated first
    """
    name: str
    description: str
    enabled: bool = True
    
    # Trigger conditions (all must be met)
    min_confidence: float = 0.0
    max_confidence: float = 1.0
    min_grounded_ratio: float = 0.0
    min_coverage: float = 0.70  # Min query coverage score required
    
    # Policy effects
    allow_paraphrasing: bool = False
    allow_implicit_inference: bool = False
    require_direct_citation: bool = True
    strict_claim_matching: bool = True
    
    # Metadata
    priority: int = 0


# ============================================================================
# Pre-defined Policies
# ============================================================================

# STRICT is the fallback - it matches everything but has lowest priority
STRICT_POLICY = VerificationPolicy(
    name="strict",
    description="Maximum fidelity - all claims must be directly cited with exact source wording",
    min_confidence=0.0,  # Matches any confidence
    min_grounded_ratio=0.0,  # Matches any ratio
    require_direct_citation=True,
    strict_claim_matching=True,
    allow_paraphrasing=False,
    allow_implicit_inference=False,
    priority=0  # Lowest priority - fallback
)

# High confidence policies have highest priority (most restrictive conditions)
HIGH_CONFIDENCE_PARAPHRASING = VerificationPolicy(
    name="high_confidence_paraphrasing",
    description="When confidence >= 90%, allow paraphrasing with semantic equivalence",
    min_confidence=0.90,
    min_grounded_ratio=0.85,
    allow_paraphrasing=True,
    require_direct_citation=True,
    strict_claim_matching=False,
    allow_implicit_inference=False,
    priority=100  # Highest priority - most specific
)

SPECULATIVE_EXAMPLES_POLICY = VerificationPolicy(
    name="speculative_examples",
    description="Allow augmented examples and implicit inferences when well-grounded (80%+ confidence, 85%+ grounded)",
    min_confidence=0.80,
    min_grounded_ratio=0.85,
    allow_paraphrasing=True,
    allow_implicit_inference=True,
    require_direct_citation=False,
    strict_claim_matching=False,
    priority=80  # Very specific conditions
)

SEMANTIC_DIRECT_POLICY = VerificationPolicy(
    name="semantic_direct",
    description="Allow semantic matches when direct matches exist (75%+ grounded)",
    min_confidence=0.75,
    min_grounded_ratio=0.75,
    allow_paraphrasing=True,
    allow_implicit_inference=False,
    strict_claim_matching=False,
    require_direct_citation=True,
    priority=60  # Medium specificity
)

RELAXED_POLICY = VerificationPolicy(
    name="relaxed",
    description="Minimal restrictions for exploratory queries - allow most flexibility",
    min_confidence=0.60,
    min_grounded_ratio=0.50,
    allow_paraphrasing=True,
    allow_implicit_inference=True,
    require_direct_citation=False,
    strict_claim_matching=False,
    priority=40  # Lower specificity, but still above STRICT
)


# ============================================================================
# Policy Engine
# ============================================================================

class PolicyEngine:
    """
    Selects and applies verification policies based on evaluation context.
    
    The engine evaluates policies in priority order (highest first) and
    selects the first policy whose trigger conditions are all met.
    
    Persona-aware: The 'scientist' persona always uses STRICT_POLICY.
    """
    
    DEFAULT_POLICIES = [
        STRICT_POLICY,
        HIGH_CONFIDENCE_PARAPHRASING,
        SEMANTIC_DIRECT_POLICY,
        SPECULATIVE_EXAMPLES_POLICY,
        RELAXED_POLICY,
    ]
    
    def __init__(self, policies: Optional[List[VerificationPolicy]] = None):
        """
        Initialize the policy engine.
        
        Args:
            policies: Custom list of policies. If None, uses DEFAULT_POLICIES.
        """
        self.policies = policies if policies is not None else self.DEFAULT_POLICIES.copy()
        # Sort by priority (highest first)
        self.policies.sort(key=lambda p: p.priority, reverse=True)
        logger.debug(f"PolicyEngine initialized with {len(self.policies)} policies")
    
    def select_policy(
        self,
        avg_confidence: float,
        grounded_ratio: float,
        query_intent: Optional[str] = None,
        persona: str = "explorer"
    ) -> VerificationPolicy:
        """
        Select the most appropriate policy based on current context.
        
        Args:
            avg_confidence: Average confidence across verified claims (0.0-1.0)
            grounded_ratio: Ratio of supported to total claims (0.0-1.0)
            query_intent: Optional intent classification (e.g., "factual", "exploratory")
            persona: Current persona ('explorer', 'intermediate', 'scientist')
            
        Returns:
            The selected VerificationPolicy
        """
        # Scientist persona ALWAYS uses strict mode
        if persona == "scientist":
            logger.debug("Scientist persona detected - forcing STRICT_POLICY")
            return STRICT_POLICY
        
        # Evaluate policies in priority order
        for policy in self.policies:
            if not policy.enabled:
                continue
            
            # Check if all trigger conditions are met
            if (avg_confidence >= policy.min_confidence and
                avg_confidence <= policy.max_confidence and
                grounded_ratio >= policy.min_grounded_ratio):
                
                logger.debug(
                    f"Selected policy '{policy.name}' for "
                    f"confidence={avg_confidence:.2f}, grounded_ratio={grounded_ratio:.2f}"
                )
                return policy
        
        # Default to strict if no policy matches
        logger.debug("No policy matched conditions - defaulting to STRICT_POLICY")
        return STRICT_POLICY
    
    def get_policy_metadata(self, policy: VerificationPolicy) -> Dict[str, Any]:
        """
        Generate metadata dictionary for a policy (for verification results).
        
        Args:
            policy: The policy to generate metadata for
            
        Returns:
            Dictionary with policy configuration suitable for JSON serialization
        """
        return {
            "policy_selected": policy.name,
            "policy_description": policy.description,
            "allow_paraphrasing": policy.allow_paraphrasing,
            "allow_implicit_inference": policy.allow_implicit_inference,
            "require_direct_citation": policy.require_direct_citation,
            "strict_claim_matching": policy.strict_claim_matching,
            "min_confidence_threshold": policy.min_confidence,
            "min_grounded_ratio_threshold": policy.min_grounded_ratio,
        }
    
    def get_all_policies_info(self) -> List[Dict[str, Any]]:
        """
        Get information about all registered policies.
        
        Returns:
            List of policy metadata dictionaries
        """
        return [
            {
                "name": p.name,
                "description": p.description,
                "enabled": p.enabled,
                "priority": p.priority,
                **self.get_policy_metadata(p)
            }
            for p in self.policies
        ]
    
    def decide(
        self,
        citation_eval: Dict[str, Any],
        coverage_eval: Dict[str, Any],
        persona: str
    ) -> Dict[str, Any]:
        """
        Derive groundedness decision and failure mode from component evaluations.
        
        Args:
            citation_eval: Result from CitationSupportEvaluator
            coverage_eval: Result from QueryCoverageEvaluator
            persona: Current persona
            
        Returns:
            Dictionary with decision (grounded, final_score, failure_mode, etc.)
        """
        # 1. Determine which policy applies based on CITATION confidence
        # Use simple selection logic for now, or reuse select_policy if appropriate
        # For simplicity, we'll re-select policy based on the new citation evaluation
        avg_confidence = citation_eval.get("citation_score", 0.0) # Use citation score as confidence proxy
        
        # Calculate grounded ratio from unsupported claims if available, else 1.0 or 0.0
        # This is a bit tricky as the new schema might not have the same structure. 
        # User said: citation_supported = false if any critical unsupported claim exists
        
        citation_supported = citation_eval.get("citation_supported", False)
        coverage_score = coverage_eval.get("coverage_score", 0.0)
        
        # Select policy (we might need to adapt select_policy to use these new inputs)
        # For now, let's use the explicit 'grounded' signal as a strong filter
        policy = self.select_policy(
            avg_confidence=avg_confidence,
            grounded_ratio=1.0 if citation_supported else 0.0, # Simplification
            persona=persona
        )
        
        # 2. Check thresholds
        min_coverage = policy.min_coverage
        
        # 3. Derive groundedness
        # grounded = (citation_supported AND coverage_score >= min_coverage)
        is_grounded = citation_supported and (coverage_score >= min_coverage)
        
        # 4. Determine failure mode
        failure_mode = "none"
        if not is_grounded:
            if not citation_supported and coverage_score >= min_coverage:
                 failure_mode = "retrieval" # Context didn't support answer, but answer addressed query
            elif citation_supported and coverage_score < min_coverage:
                 failure_mode = "reasoning" # Context supported answer, but answer missed query intent
            elif not citation_supported and coverage_score < min_coverage:
                 failure_mode = "mixed"
        
        # 5. Compute final score (weighted average? or min?)
        # User said: Stabilizes metrics. Let's use a weighted combo or just the lower of the two.
        # Let's simple average for now, or just citation score if covered? 
        # User didn't specify exact final_score math, but said "score from LLM outputs entirely" is removed.
        # "final_score" in the example output: 0.87. 
        # Let's average them.
        final_score = (citation_eval.get("citation_score", 0.0) + coverage_score) / 2.0
        
        return {
            "grounded": is_grounded,
            "final_score": final_score,
            "failure_mode": failure_mode,
            "policy_applied": policy.name,
            "policy_min_coverage": min_coverage
        }


# ============================================================================
# Persona-Specific Policy Overrides
# ============================================================================

def get_persona_policy_config(persona: str) -> Dict[str, Any]:
    """
    Get default policy configuration for a specific persona.
    
    Args:
        persona: One of 'explorer', 'intermediate', 'scientist'
        
    Returns:
        Dictionary with policy settings for the persona
    """
    configs = {
        'explorer': {
            'allow_paraphrasing_at_confidence': 0.85,
            'allow_semantic_direct': True,
            'allow_speculative_examples': True,
            'strict_only_mode': False,
            'default_policy': 'relaxed',
        },
        'intermediate': {
            'allow_paraphrasing_at_confidence': 0.90,
            'allow_semantic_direct': True,
            'allow_speculative_examples': False,
            'strict_only_mode': False,
            'default_policy': 'semantic_direct',
        },
        'scientist': {
            'allow_paraphrasing_at_confidence': None,  # Never allow
            'allow_semantic_direct': False,
            'allow_speculative_examples': False,
            'strict_only_mode': True,
            'default_policy': 'strict',
        },
    }
    
    return configs.get(persona, configs['explorer'])
