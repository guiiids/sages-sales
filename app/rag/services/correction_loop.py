"""
Correction Loop Service (DEPRECATED)

⚠️ DEPRECATED: This binary groundedness-based correction loop is deprecated.
Use services/radar_correction_loop.py for multi-dimensional correction with
engagement preservation. The RADAR loop provides:
- 6-axis quality evaluation instead of binary pass/fail
- Warmer prompts with higher temperature (0.6 vs 0.3)
- Dimension-specific correction guidance
- Preservation of conversational tone

Orchestrates the draft → evaluate → correct → final flow for the Scientist persona.
Uses the groundedness checker to identify issues and sends recommendations back
to the LLM for correction.
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional, Dict, Any

from app.rag.services.groundedness_checker import GroundednessChecker, EvaluationResult

logger = logging.getLogger(__name__)


@dataclass
class CorrectionResult:
    """Result from the correction loop."""
    final_response: str           # Corrected or original response
    was_corrected: bool           # Whether correction was applied
    original_draft: str           # The original draft before correction
    evaluation: Dict[str, Any]    # Groundedness evaluation result
    correction_prompt: Optional[str] = None  # The repair prompt used (if corrected)
    rounds_used: int = 0          # How many correction rounds were executed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_response": self.final_response,
            "was_corrected": self.was_corrected,
            "original_draft": self.original_draft,
            "evaluation": self.evaluation,
            "correction_prompt": self.correction_prompt,
            "rounds_used": self.rounds_used
        }


class CorrectionLoop:
    """
    Orchestrates the correction flow for Scientist persona responses.

    Flow:
    1. Evaluate draft with groundedness checker
    2. If score < threshold and recommendations exist:
       - Build a repair prompt with specific fixes
       - Send draft + recommendations back to LLM
       - Return corrected response
    3. Otherwise return original draft
    """

    CORRECTION_PROMPT = """You are a precision editor for a RAG system. Your task is to correct a draft response based on specific issues identified by a fact-checker.

## Context (Source Material)
{context}

## Original Question
{query}

## Draft Response (Needs Correction)
{draft}

## Issues Identified by Fact-Checker

### Unsupported Claims (Score: {score:.2f})
{unsupported_claims}

### Recommendations
{recommendations}

## Instructions

1. **Remove or Revise**: For each unsupported claim, either:
   - Remove it entirely if there's no source support
   - Revise it to match what the sources actually say
   - Add qualifying language (e.g., "based on general knowledge" or "not found in sources")

2. **Preserve Accuracy**: Keep all supported claims intact.

3. **Maintain Citations**: Ensure all citations [n] reference valid source IDs.

4. **Keep the Response Helpful**: The corrected response should still answer the question as completely as possible using only grounded information.

## Output

Provide the CORRECTED response only. Do not include explanations or meta-commentary about the corrections."""

    def __init__(
        self,
        checker: Optional[GroundednessChecker] = None,
        llm_client = None,
        deployment_name: Optional[str] = None
    ):
        """
        Initialize the correction loop.

        Args:
            checker: GroundednessChecker instance (created from env if not provided)
            llm_client: Azure OpenAI client (created from env if not provided)
            deployment_name: LLM deployment to use for corrections
        """
        self.checker = checker or GroundednessChecker.from_env()
        self.deployment_name = deployment_name or os.getenv("CHAT_DEPLOYMENT", "gpt-4o")

        if llm_client:
            self._client = llm_client
        else:
            self._init_client()

    def _init_client(self):
        """Initialize Azure OpenAI client from environment."""
        try:
            from openai import AzureOpenAI
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            api_key = os.getenv("AZURE_OPENAI_KEY") or os.getenv("AZURE_OPENAI_API_KEY")

            if endpoint and api_key:
                self._client = AzureOpenAI(
                    azure_endpoint=endpoint,
                    api_key=api_key,
                    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
                )
            else:
                logger.warning("Azure OpenAI credentials not configured for correction loop")
                self._client = None
        except Exception as e:
            logger.error(f"Failed to initialize correction loop LLM client: {e}")
            self._client = None

    def correct_response(
        self,
        draft: str,
        query: str,
        context: str,
        query_id: int,
        max_rounds: int = 1,
        threshold: float = 0.75,
        persona: str = "scientist",
    ) -> CorrectionResult:
        """
        Evaluate a draft response and apply corrections if needed.

        Args:
            draft: The draft response to evaluate
            query: The original question
            context: The source context
            max_rounds: Maximum correction attempts (each round re-evaluates)
            threshold: Score threshold below which correction is triggered
            persona: Current persona for policy selection (default: scientist)

        Returns:
            CorrectionResult with final response and metadata
        """
        current_response = draft
        rounds_used = 0
        last_evaluation = None
        correction_prompt = None
        was_corrected = False

        for round_num in range(max_rounds):
            # Evaluate current response
            evaluation = self.checker.evaluate_response(
                query=query,
                answer=current_response,
                context=context,
                threshold=threshold,
                persona=persona,
                query_id=query_id
            )
            last_evaluation = evaluation.to_dict()

            logger.info(f"Correction round {round_num + 1}: score={evaluation.score:.2f}, grounded={evaluation.grounded}")

            # Check failure mode - skip correction if it's a retrieval failure
            # If the context doesn't support the answer, asking the LLM to "fix" it usually leads to hallucination
            if getattr(evaluation, "failure_mode", "none") == "retrieval":
                logger.info("Skipping correction: Failure mode is 'retrieval' (context missing, cannot fix via rewriting)")
                # We might want to attach a warning to the result, but for now just breaking preserves the original
                break

            # Check if correction is needed
            if evaluation.grounded:
                logger.info(f"Response is grounded, no correction needed")
                break

            # Check if we have actionable recommendations
            if not evaluation.unsupported_claims and not evaluation.recommendations:
                logger.info("No recommendations available for correction")
                break

            # Check if LLM client is available
            if self._client is None:
                logger.warning("LLM client not available for correction")
                break

            # Build correction prompt
            correction_prompt = self._build_correction_prompt(
                draft=current_response,
                query=query,
                context=context,
                evaluation=evaluation
            )

            # Apply correction
            try:
                corrected = self._apply_correction(correction_prompt)
                if corrected and corrected.strip():
                    current_response = corrected
                    was_corrected = True
                    rounds_used = round_num + 1
                    logger.info(f"Correction applied in round {round_num + 1}")
                else:
                    logger.warning("Correction returned empty response, keeping original")
                    break
            except Exception as e:
                logger.error(f"Correction failed in round {round_num + 1}: {e}")
                break

        return CorrectionResult(
            final_response=current_response,
            was_corrected=was_corrected,
            original_draft=draft,
            evaluation=last_evaluation or {},
            correction_prompt=correction_prompt if was_corrected else None,
            rounds_used=rounds_used
        )

    def _build_correction_prompt(
        self,
        draft: str,
        query: str,
        context: str,
        evaluation: EvaluationResult
    ) -> str:
        """Build the correction prompt from evaluation results."""
        # Format unsupported claims
        unsupported_text = ""
        for i, claim in enumerate(evaluation.unsupported_claims, 1):
            if isinstance(claim, dict):
                unsupported_text += f"{i}. **Claim**: {claim.get('claim', '')}\n"

                # Use reason if available, otherwise construct from support_level + severity
                reason = claim.get('reason')
                if not reason:
                    support = claim.get('support_level', 'none')
                    severity = claim.get('severity', 'unknown')
                    reason = f"Support: {support}, Severity: {severity}"
                unsupported_text += f"   **Issue**: {reason}\n"

                # Use recommendation as the fix
                if claim.get('recommendation'):
                    unsupported_text += f"   **Fix**: {claim.get('recommendation')}\n"
            else:
                unsupported_text += f"{i}. {claim}\n"

        if not unsupported_text:
            unsupported_text = "(None identified)"

        # Format recommendations
        recs_text = ""
        for i, rec in enumerate(evaluation.recommendations, 1):
            recs_text += f"{i}. {rec}\n"

        if not recs_text:
            recs_text = "(No specific recommendations)"

        return self.CORRECTION_PROMPT.format(
            context=context[:10000],  # Limit context for correction
            query=query,
            draft=draft,
            score=evaluation.score,
            unsupported_claims=unsupported_text,
            recommendations=recs_text
        )

    def _apply_correction(self, correction_prompt: str) -> Optional[str]:
        """Send correction prompt to LLM and return corrected response."""
        response = self._client.chat.completions.create(
            model=self.deployment_name,
            messages=[{"role": "user", "content": correction_prompt}],
            max_completion_tokens=2000,  # GPT-5.x requires max_completion_tokens
            temperature=0.3  # Lower temperature for precise corrections
        )

        return response.choices[0].message.content

    @classmethod
    def from_env(cls) -> 'CorrectionLoop':
        """Create CorrectionLoop from environment variables."""
        return cls()