"""
Groundedness Checker Service

Evaluates if a generated answer is supported by the provided context.
Simplified port from v1r1, focused on claim extraction and recommendations.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from app.Connection import get_connection
from app.models.models import GroundednessEvaluation

logger = logging.getLogger(__name__)

# Import PolicyEngine for confidence-based flexibility
try:
    from app.rag.services.verification_policies import PolicyEngine, STRICT_POLICY
except ImportError:
    # Fallback for standalone usage
    PolicyEngine = None
    STRICT_POLICY = None


@dataclass
class EvaluationResult:
    """Result from groundedness evaluation with intent fulfillment assessment."""
    grounded: bool
    score: float  # 0.0 - 1.0
    confidence: float  # 0.0 - 1.0
    supported_claims: List[str] = field(default_factory=list)
    unsupported_claims: List[Dict[str, str]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    evaluation_summary: str = ""
    citation_audit: Optional[Dict[str, Any]] = None
    warning_info: Dict[str, Any] = field(default_factory=lambda: {"level": "none", "message": ""})

    # NEW: Intent and Question Fulfillment Metrics
    question_addressed: bool = True           # Does the answer address the question?
    question_addressed_score: float = 1.0     # 0.0-1.0 how directly it's addressed
    intent_fulfillment: bool = True           # Can user complete their intent?
    intent_fulfillment_score: float = 1.0     # 0.0-1.0 completeness for user goal
    intent_gaps: List[str] = field(default_factory=list)  # What's missing for intent

    # NEW: Policy Flags and Metadata
    policies_applied: Dict[str, Any] = field(default_factory=dict)

    # NEW: Derived Decision Fields
    failure_mode: str = "none" # "none" | "retrieval" | "reasoning" | "mixed"
    scope_issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grounded": self.grounded,
            "score": self.score,
            "confidence": self.confidence,
            "supported_claims": self.supported_claims,
            "unsupported_claims": self.unsupported_claims,
            "recommendations": self.recommendations,
            "evaluation_summary": self.evaluation_summary,
            "citation_audit": self.citation_audit,
            "warning_info": self.warning_info,
            # Intent and question fulfillment
            "question_addressed": self.question_addressed,
            "question_addressed_score": self.question_addressed_score,
            "intent_fulfillment": self.intent_fulfillment,
            "intent_fulfillment_score": self.intent_fulfillment_score,
            "intent_gaps": self.intent_gaps,
            # Policy metadata
            "policies_applied": self.policies_applied,
            # Derived decision
            "failure_mode": self.failure_mode,
            "scope_issues": self.scope_issues
        }


class GroundednessChecker:
    """
    Evaluates if generated answers are grounded in the provided context.
    Acts as a coordinator for orthogonal evaluations:
    1. Citation Support (Evidence <-> Answer)
    2. Query Coverage (Query <-> Answer)
    3. Decision Layer (Derived from 1 & 2 via PolicyEngine)
    """

    CITATION_SUPPORT_PROMPT = """You are an expert evidence auditor.

You will be given:
- A generated answer
- Source context that was retrieved

Your task:
- Identify all factual claims in the answer
- Determine whether each claim is explicitly supported by the source context

Rules:
- Do NOT evaluate whether the answer addresses the user question
- Do NOT judge usefulness or completeness
- Logical inference is allowed but must be labeled as inferred
- If a claim is not directly or inferentially supported, mark it unsupported

Output valid JSON only.
Output format:
{
  "citation_supported": true,
  "citation_score": 0.0,
  "unsupported_claims": [
    {
      "claim": "string",
      "support_level": "none | partial | inferred",
      "severity": "critical | moderate | minor",
      "recommendation": "string"
    }
  ],
  "evidence_notes": [
    "optional free-text notes about ambiguity or inference"
  ]
}
"""

    QUERY_COVERAGE_PROMPT = """You are an intent and coverage evaluator.

You will be given:
- A user question
- A generated answer

Your task:
- Determine whether the answer addresses what the user asked
- Identify missing parts needed to fully satisfy the intent

Rules:
- Do NOT consider citations or evidence
- Do NOT judge factual correctness
- Focus only on relevance, scope, and completeness

Output valid JSON only.
Output format:
{
  "question_addressed": true,
  "coverage_score": 0.0,
  "intent_fulfillment": true,
  "intent_gaps": [
    "string"
  ],
  "scope_issues": [
    "too broad | too narrow | answered different question"
  ]
}
"""

    def __init__(
        self,
        azure_endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        api_version: str = "2024-12-01-preview",
        deployment_name: str = "gpt-4o",
        max_tokens: int = 5000,
        temperature: float = 0.0
    ):
        self.azure_endpoint = azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = api_key or os.getenv("AZURE_OPENAI_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
        self.api_version = api_version
        self.deployment_name = os.getenv("CHAT_DEPLOYMENT", deployment_name)
        self.max_tokens = int(os.getenv("GROUNDEDNESS_MAX_TOKENS", str(max_tokens)))
        self.temperature = float(os.getenv("GROUNDEDNESS_TEMPERATURE", str(temperature)))

        self._client = None
        self._policy_engine = PolicyEngine() if PolicyEngine else None
        self._init_client()

    def _init_client(self):
        """Initialize Azure OpenAI client."""
        if not self.azure_endpoint or not self.api_key:
            logger.warning("Azure OpenAI credentials not configured for groundedness checker")
            return

        try:
            from openai import AzureOpenAI
            self._client = AzureOpenAI(
                azure_endpoint=self.azure_endpoint,
                api_key=self.api_key,
                api_version=self.api_version
            )
            logger.info(f"GroundednessChecker initialized with deployment: {self.deployment_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Azure OpenAI client: {e}")
            self._client = None

    def evaluate_response(
        self,
        query: str,
        answer: str,
        context: str,
        query_id: int,
        threshold: float = 0.75,
        persona: str = "explorer",
    ) -> EvaluationResult:
        """
        Evaluate if the answer is grounded in the context.

        Args:
            query: The original question
            answer: The generated answer to evaluate
            context: The source context used for generation
            threshold: Score threshold (deprecated, derived by policy)
            persona: Current persona for policy selection ('explorer', 'intermediate', 'scientist')

        Returns:
            EvaluationResult with derived grounding status
        """
        groundness_check_start_time = time.time()
        # Quick validation checks
        if not answer or not answer.strip():
            return EvaluationResult(
                grounded=True,
                score=1.0,
                confidence=1.0,
                evaluation_summary="Empty answer - trivially grounded"
            )

        if not context or not context.strip():
            return EvaluationResult(
                grounded=False,
                score=0.0,
                confidence=0.0,
                recommendations=["No context provided - cannot verify claims"],
                evaluation_summary="No context available for evaluation",
                failure_mode="retrieval"
            )

        # Run citation audit (deterministic, no LLM call)
        citation_audit = self._audit_citations(answer, context)

        # If no LLM client, return basic result based on citation audit
        if self._client is None:
            return EvaluationResult(
                grounded=citation_audit.get("citation_ok", False),
                score=citation_audit.get("coverage_ratio", 0.0),
                confidence=0.5,
                citation_audit=citation_audit,
                recommendations=["LLM client not configured - using citation audit only"],
                evaluation_summary="Citation-only evaluation (no LLM available)",
                failure_mode="retrieval" if not citation_audit.get("citation_ok", False) else "none"
            )

        # Run split evaluations
        try:
            # 1. Evaluate Citation Support
            citation_eval = self._evaluate_citation_support(answer, context)
            citation_eval["citation_audit"] = citation_audit

            # 2. Evaluate Query Coverage
            coverage_eval = self._evaluate_query_coverage(query, answer)

            # 3. Derive Decision via Policy Engine
            if self._policy_engine:
                decision = self._policy_engine.decide(
                    citation_eval=citation_eval,
                    coverage_eval=coverage_eval,
                    persona=persona
                )
            else:
                # Fallback logic if no policy engine
                grounded = citation_eval.get("citation_supported", False)
                decision = {
                    "grounded": grounded,
                    "final_score": citation_eval.get("citation_score", 0.0),
                    "failure_mode": "none" if grounded else "mixed",
                    "policy_applied": "LEGACY_FALLBACK"
                }

            # Extract lists for result
            unsupported_claims_list = citation_eval.get("unsupported_claims", [])

            # Collect recommendations from each claim
            recs = []
            for claim in unsupported_claims_list:
                if isinstance(claim, dict) and claim.get("recommendation"):
                    recs.append(claim["recommendation"])

            # Include evidence_notes as additional recommendations
            if citation_eval.get("evidence_notes"):
                recs.extend(citation_eval["evidence_notes"])


            # 4. Construct Result
            result = EvaluationResult(
                grounded=decision["grounded"],
                score=decision["final_score"],
                confidence=citation_eval.get("citation_score", 0.0),
                supported_claims=[],
                unsupported_claims=unsupported_claims_list,
                recommendations=recs,
                evaluation_summary=f"Policy: {decision.get('policy_applied')} Mode: {decision['failure_mode']}",
                citation_audit=citation_audit,
                question_addressed=coverage_eval.get("question_addressed", True),
                question_addressed_score=coverage_eval.get("coverage_score", 0.0),
                intent_fulfillment=coverage_eval.get("intent_fulfillment", True),
                intent_gaps=coverage_eval.get("intent_gaps", []),
                scope_issues=coverage_eval.get("scope_issues", []),
                failure_mode=decision["failure_mode"],
                policies_applied={"policy_name": decision.get("policy_applied"), "full_decision": decision}
            )
            groundness_check_end_time = time.time()
            latency_ms = int((groundness_check_end_time - groundness_check_start_time) * 1000)
            # Save evaluation to DB
            connection = get_connection()
            grouness_evaluation = GroundednessEvaluation(
                query_id = query_id,
                answer = answer,
                context_snippet = context[:2000] if context else None,
                grounded=result.grounded,
                score=result.score,
                confidence=result.confidence,
                failure_mode=result.failure_mode,
                unsupported_claims=result.unsupported_claims,
                recommendations=result.recommendations,
                intent_fulfillment=result.intent_fulfillment,
                intent_gaps=result.intent_gaps,
                evaluation_summary=result.evaluation_summary,
                citation_audit=result.citation_audit,
                policies_applied=result.policies_applied,
                model=self.deployment_name,
                latency_ms=latency_ms
            )

            connection.save_groundenss_evaluation(grouness_evaluation)

            return result

        except Exception as e:
            logger.error(f"Groundedness evaluation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return EvaluationResult(
                grounded=True,  # Fail open
                score=0.5,
                confidence=0.0,
                citation_audit=citation_audit,
                recommendations=[f"Evaluation failed: {str(e)}"],
                evaluation_summary=f"Error during evaluation: {str(e)}",
                failure_mode="mixed"
            )

    def _evaluate_citation_support(self, answer: str, context: str) -> Dict[str, Any]:
        """Run Citation Support Evaluation."""
        prompt = self.CITATION_SUPPORT_PROMPT + f"\n\n## Context\n{context[:15000]}\n\n## Generated Answer\n{answer}"
        response = self._call_llm(prompt)
        return self._parse_json_safe(response)

    def _evaluate_query_coverage(self, query: str, answer: str) -> Dict[str, Any]:
        """Run Query Coverage Evaluation."""
        prompt = self.QUERY_COVERAGE_PROMPT + f"\n\n## User Question\n{query}\n\n## Generated Answer\n{answer}"
        response = self._call_llm(prompt)
        return self._parse_json_safe(response)

    def _call_llm(self, prompt: str, retry_count: int = 0) -> str:
        """Helper to call LLM with retry on empty response."""
        is_gpt5 = 'gpt-5' in self.deployment_name.lower() or 'o4' in self.deployment_name.lower()
        max_retries = 2

        if is_gpt5:
            response = self._client.chat.completions.create(
                model=self.deployment_name,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=self.max_tokens,
                temperature=self.temperature
            )
        else:
            response = self._client.chat.completions.create(
                model=self.deployment_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )

        content = response.choices[0].message.content or ""

        # Retry on empty response (common cause of JSON parse errors)
        if not content.strip() and retry_count < max_retries:
            logger.warning(f"Empty LLM response, retrying ({retry_count + 1}/{max_retries})")
            import time
            time.sleep(0.5)  # Brief backoff
            return self._call_llm(prompt, retry_count + 1)

        return content

    def _parse_json_safe(self, text: str) -> Dict[str, Any]:
        """Robus JSON extraction."""
        try:
            text = text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

            start_idx = text.find('{')
            end_idx = text.rfind('}')

            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                text = text[start_idx : end_idx + 1]

            return json.loads(text)
        except Exception as e:
            logger.error(f"JSON parse error: {e}")
            return {}  # Return empty dict on failure

    # Legacy helper removed/replaced


    def _audit_citations(self, answer: str, context: str) -> Dict[str, Any]:
        """
        Deterministic citation audit - no LLM call.
        Checks if inline citations [n] in the answer match source IDs in the context.
        """
        # Extract citation IDs from answer [1], [2], etc.
        citation_pattern = r'\[(\d+)\]'
        cited_ids = set(re.findall(citation_pattern, answer))

        # Extract source IDs from context <source id="n">
        source_pattern = r'<source\s+id=["\']?(\d+)["\']?>'
        context_ids = set(re.findall(source_pattern, context))

        # Calculate coverage
        if not cited_ids:
            has_citations = False
            coverage_ratio = 0.0
        else:
            has_citations = True
            # What fraction of cited sources are in the context?
            valid_cites = cited_ids & context_ids
            coverage_ratio = len(valid_cites) / len(cited_ids) if cited_ids else 0.0

        # Find issues
        missing_ids = cited_ids - context_ids  # Cited but not in context
        unused_ids = context_ids - cited_ids   # In context but not cited

        return {
            "has_any_citations": has_citations,
            "citation_ids_present": sorted(cited_ids),
            "citation_ids_in_context": sorted(context_ids),
            "missing_ids": sorted(missing_ids),
            "unused_context_ids": sorted(unused_ids),
            "coverage_ratio": coverage_ratio,
            "citation_ok": len(missing_ids) == 0  # No invalid citations
        }

    def _apply_policy_adjustments(
        self,
        result: EvaluationResult,
        persona: str
    ) -> EvaluationResult:
        """
        Deprecated - moved to PolicyEngine.decide, but kept as shim if needed.
        """
        return result

        # Original logic removed in favor of derived decision in PolicyEngine
        if not self._policy_engine:
            return result

        # Calculate grounded ratio from claims
        total_claims = len(result.supported_claims) + len(result.unsupported_claims)
        grounded_ratio = len(result.supported_claims) / total_claims if total_claims > 0 else 1.0

        # Select appropriate policy based on confidence and grounded ratio
        policy = self._policy_engine.select_policy(
            avg_confidence=result.confidence,
            grounded_ratio=grounded_ratio,
            persona=persona
        )

        # Build and attach policy metadata
        result.policies_applied = self._build_verification_metadata(result, policy)

        # Apply policy effects
        if policy.allow_paraphrasing and result.confidence >= 0.90:
            # Promote moderate-severity unsupported claims to supported
            # These are semantic equivalents that shouldn't penalize
            promoted_claims = []
            remaining_unsupported = []

            for claim_info in result.unsupported_claims:
                severity = claim_info.get("severity", "unknown")
                if severity in ("minor", "moderate") and policy.allow_paraphrasing:
                    # Promote this claim - it's semantically equivalent
                    promoted_claims.append(claim_info.get("claim", str(claim_info)))
                    logger.debug(f"Policy promoted claim: {claim_info.get('claim', '')[:50]}...")
                else:
                    remaining_unsupported.append(claim_info)

            if promoted_claims:
                result.supported_claims = result.supported_claims + promoted_claims
                result.unsupported_claims = remaining_unsupported

                # Recalculate score based on new claim distribution
                new_total = len(result.supported_claims) + len(result.unsupported_claims)
                if new_total > 0:
                    result.score = len(result.supported_claims) / new_total
                    result.grounded = result.score >= 0.75

                logger.info(
                    f"Policy '{policy.name}' promoted {len(promoted_claims)} claims "
                    f"(new score: {result.score:.2f})"
                )

        return result

    def _build_verification_metadata(
        self,
        result: EvaluationResult,
        policy
    ) -> Dict[str, Any]:
        """
        Build comprehensive verification metadata aligned with self_judge.py patterns.

        Args:
            result: Current evaluation result
            policy: Selected verification policy

        Returns:
            Dictionary with policy and evaluation metadata
        """
        total_claims = len(result.supported_claims) + len(result.unsupported_claims)

        return {
            "enabled": True,

            # Policy selection
            "policy_selected": policy.name if policy else "none",
            "policy_description": policy.description if policy else "",

            # Claim statistics
            "total_claims": total_claims,
            "supported_claims_count": len(result.supported_claims),
            "unsupported_claims_count": len(result.unsupported_claims),
            "grounded_ratio": len(result.supported_claims) / total_claims if total_claims > 0 else 1.0,
            "average_confidence": result.confidence,

            # Intent and Question Assessment
            "question_assessment": {
                "addressed": result.question_addressed,
                "score": result.question_addressed_score,
            },
            "intent_assessment": {
                "fulfilled": result.intent_fulfillment,
                "score": result.intent_fulfillment_score,
                "gaps": result.intent_gaps,
            },

            # Policies applied
            "policies_applied": result.policies_applied
        }

    @classmethod
    def from_env(cls) -> 'GroundednessChecker':
        """Create GroundednessChecker from environment variables."""
        return cls(
            azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT'),
            api_key=os.getenv('AZURE_OPENAI_KEY') or os.getenv('AZURE_OPENAI_API_KEY'),
            api_version=os.getenv('AZURE_OPENAI_API_VERSION', '2024-12-01-preview'),
            deployment_name=os.getenv('CHAT_DEPLOYMENT', 'gpt-4o')
        )
