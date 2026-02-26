"""
RADAR-Based Correction Loop Service

Multi-dimensional correction loop that uses RADAR (6-axis evaluation) to identify
specific quality issues and applies targeted corrections while preserving
conversational warmth and engagement.

Unlike the binary groundedness correction loop, this service:
- Evaluates across 6 independent quality dimensions
- Only corrects specific failing dimensions
- Uses warmer prompts with higher temperature for natural flow
- Preserves what works, enhances what's broken

===============================================================================
PIPELINE INVARIANT (DO NOT INVERT):

    Draft → Groundedness evaluation → RADAR correction → Final answer

RADAR is a SOFT SHAPER for quality. It must NEVER:
  - Block or delete claims based on "unsupported evidence"
  - Act as a truth gate (that's Groundedness' job)
  - Reference "support", "evidence", "verification", or "sources" when judging

Groundedness is the HARD GATE for truth. Only Groundedness decides:
  - "Can I trust this claim?"
  - "Is this claim allowed to ship?"

RADAR only shapes AFTER Groundedness has passed:
  - "How good is this answer, given it's allowed?"
  - "What stylistic improvements can we make?"
===============================================================================
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Union

from app.rag.openai_service import OpenAIService

logger = logging.getLogger(__name__)


@dataclass
class RadarCorrectionResult:
    """Result from the RADAR correction loop."""
    final_response: str           # Corrected or original response
    was_corrected: bool           # Whether correction was applied
    original_draft: str           # The original draft before correction
    radar_scores: Dict[str, float]  # Dimension scores {name: score}
    radar_reasons: Dict[str, str]   # Dimension reasons {name: reason} - NEW for logging
    failing_dimensions: List[str]  # Dimensions below threshold
    correction_prompt: Optional[str] = None  # The repair prompt used (if corrected)
    rounds_used: int = 0          # How many correction rounds were executed
    # Token usage tracking
    eval_prompt_tokens: int = 0      # Tokens for evaluation prompt
    eval_completion_tokens: int = 0  # Tokens for evaluation response
    correction_prompt_tokens: int = 0     # Tokens for correction prompt (if corrected)
    correction_completion_tokens: int = 0 # Tokens for correction response (if corrected)
    
    @property
    def total_radar_tokens(self) -> int:
        """Total tokens used by RADAR (evaluation + correction)."""
        return (self.eval_prompt_tokens + self.eval_completion_tokens + 
                self.correction_prompt_tokens + self.correction_completion_tokens)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_response": self.final_response,
            "was_corrected": self.was_corrected,
            "original_draft": self.original_draft,
            "radar_scores": self.radar_scores,
            "radar_reasons": self.radar_reasons,
            "failing_dimensions": self.failing_dimensions,
            "correction_prompt": self.correction_prompt,
            "rounds_used": self.rounds_used,
            "eval_prompt_tokens": self.eval_prompt_tokens,
            "eval_completion_tokens": self.eval_completion_tokens,
            "correction_prompt_tokens": self.correction_prompt_tokens,
            "correction_completion_tokens": self.correction_completion_tokens,
            "total_radar_tokens": self.total_radar_tokens
        }


class RadarCorrectionLoop:
    """
    RADAR-based correction loop for Scientist persona responses.
    
    Uses multi-dimensional quality evaluation to:
    1. Identify specific weak dimensions (factual accuracy, query resolution, etc.)
    2. Apply targeted corrections with dimension-specific guidance
    3. Preserve warmth and engagement through higher temperature and conversational prompts
    
    Flow:
    1. Evaluate draft with RADAR (6 dimensions)
    2. If any dimension < threshold:
       - Build dimension-specific warm correction prompt
       - Apply correction with temperature 0.6
    3. Return corrected or original response
    """
    
    # Default per-dimension thresholds
    # NOTE: These are QUALITY thresholds, not TRUTH thresholds.
    # Truth verification belongs to Groundedness, not RADAR.
    DEFAULT_THRESHOLDS = {
        'query_resolution': 0.70,    # Must directly answer the question
        'scope_discipline': 0.70,    # No overclaiming or overconfidence (NOT truth verification)
        'completeness': 0.70,        # Must cover key aspects
        'clarity': 0.60,             # Lower bar - readability
        'actionability': 0.65,       # Nice to have
        'citation_hygiene': 0.80,    # Citation formatting only (NOT evidence verification)
    }
    
    # Warm correction prompt that preserves engagement
    WARM_CORRECTION_PROMPT = """You are a helpful, knowledgeable assistant who wants to provide the most accurate AND engaging response possible.

## Original Question
{query}

## Your Draft Response
{draft}

## Source Material
{context}

## Quality Assessment

I've analyzed your draft and found some opportunities to improve:

{dimension_feedback}

## Your Task: Enhance While Preserving Warmth

Please revise your response to address these issues while MAINTAINING:
- ✅ Conversational, friendly tone
- ✅ Natural flow and readability
- ✅ Helpfulness and clarity
- ✅ Appropriate level of detail
{verbosity_instruction}

### Specific Guidelines

{dimension_instructions}

### Critical Rules
1. **Keep what works**: Don't change well-supported, clear sections
2. **Enhance, don't strip**: If removing unsupported claims, replace with helpful alternatives when possible
3. **Cite properly**: Use [n] citations for all factual claims drawn from the sources
4. **Stay warm**: Write like you're helping a colleague, not drafting legal text
5. **Be complete**: Answer the question fully, don't just remove problems
6. **Don't exaggerate corrections**: Make proportional, reasonable improvements—don't go overboard just to satisfy a dimension. If actionability was low, add a brief next step, don't fabricate a 10-item action plan. Keep the revision as a natural increment, not a dramatic rewrite.

## Output
Provide your REVISED response. Make it better on all fronts: more accurate, clearer, AND more engaging."""

    # Verbosity-specific instructions injected into the correction prompt
    VERBOSITY_INSTRUCTIONS = {
        'low': """\n- ⚠️ **CRITICAL VERBOSITY CONSTRAINT: LOW** — The user chose "low" verbosity.
  Your revised response MUST be concise and SHORT. Do NOT expand, elaborate, or add new sections.
  Match or reduce the length of the original draft. Cut filler, merge bullets, remove redundancy.""",
        'medium': """\n- 📏 **VERBOSITY: MEDIUM** — Keep balanced detail. Don't significantly expand beyond the draft length.""",
        'high': """\n- 📖 **VERBOSITY: HIGH** — You may provide thorough, detailed explanations with full context.""",
    }

    # Dimension-specific feedback templates
    # NOTE: These provide quality improvement feedback, NOT truth verification.
    DIMENSION_FEEDBACK = {
        'scope_discipline': """📊 **Scope Discipline: {score:.0%}**
The response contains overclaiming or unnecessary certainty:
{details}

💡 Tip: Soften overconfident language. Use "Based on the documentation..." or add caveats like "While not specified, typically..." Don't delete claims—just narrow scope.
""",
        'query_resolution': """🎯 **Query Resolution: {score:.0%}**
Your response drifted from the core question.
The user specifically asked: "{query}"

💡 Tip: Start with a direct answer, then provide supporting details.
""",
        'completeness': """📋 **Completeness: {score:.0%}**
The response is missing some important aspects:
{details}

💡 Tip: Cover all key steps and mention important caveats. Note: Saying "I couldn't find information about X" is NOT a completeness failure.
""",
        'clarity': """✨ **Clarity: {score:.0%}**
The response could be better organized:
- Use bullet points for steps
- Add clear section headers
- Define technical terms

💡 Tip: Imagine explaining this to a colleague over coffee.
""",
        'actionability': """⚡ **Actionability: {score:.0%}**
The response lacks concrete next steps.

💡 Tip: End with specific actions the user can take immediately.
""",
        'citation_hygiene': """🔗 **Citation Hygiene: {score:.0%}**
Citation formatting needs correction:
{details}

💡 Tip: Ensure all [n] references are syntactically valid and match actual source IDs. Remove dangling or fake citations.
"""
    }

    def __init__(
        self,
        openai_service: Optional[OpenAIService] = None,
        thresholds: Optional[Dict[str, float]] = None,
        temperature: float = 0.6,
        max_rounds: int = 1,
        # Persona-aware Responses API settings
        use_responses_api: bool = False,
        verbosity: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        responses_api_version: str = '2025-03-01-preview',
    ):
        """
        Initialize the RADAR correction loop.
        
        Args:
            openai_service: OpenAI service for LLM calls (created from env if not provided)
            thresholds: Per-dimension score thresholds (uses defaults if not provided)
            temperature: Temperature for correction (higher = more natural) - default 0.6
            max_rounds: Maximum correction attempts - default 1
            use_responses_api: If True, correction phase uses Responses API (preserves verbosity)
            verbosity: Persona verbosity level ('low', 'medium', 'high')
            reasoning_effort: Persona reasoning effort ('low', 'medium', 'high')
            responses_api_version: API version for Responses API
        """
        self.openai_service = openai_service or self._init_openai_service()
        self.thresholds = thresholds or self._verbosity_adjusted_thresholds(verbosity)
        self.temperature = temperature
        self.max_rounds = max_rounds
        self.use_responses_api = use_responses_api
        self.verbosity = verbosity
        self.reasoning_effort = reasoning_effort
        self.responses_api_version = responses_api_version
    
    def _verbosity_adjusted_thresholds(self, verbosity: Optional[str] = None) -> Dict[str, float]:
        """Return thresholds adjusted for verbosity level.
        
        Low-verbosity responses have less room for detail, so completeness
        and actionability thresholds are relaxed to avoid false-positive corrections.
        """
        thresholds = self.DEFAULT_THRESHOLDS.copy()
        
        if verbosity == 'low':
            # Relax dimensions that require space to do well
            thresholds['completeness'] = 0.50       # Was 0.70 — can't be exhaustive in ~800 tokens
            thresholds['actionability'] = 0.50       # Was 0.65 — less room for next-steps lists
            logger.info(f"[RADAR] Thresholds relaxed for verbosity='low': completeness={thresholds['completeness']}, actionability={thresholds['actionability']}")
        elif verbosity == 'medium':
            thresholds['completeness'] = 0.60       # Slight relaxation from 0.70
        # 'high' keeps defaults
        
        return thresholds
    
    def _get_verbosity_eval_context(self) -> str:
        """Return a prompt section that informs the evaluator about verbosity constraints."""
        if self.verbosity == 'low':
            return """
## Verbosity Context: LOW
The response was generated with VERBOSITY=LOW. The model was explicitly instructed to be
concise and brief. When scoring, account for the following:
- **Completeness**: A short, focused answer that covers the core question IS complete.
  Do NOT penalize for omitting secondary details, extended explanations, or exhaustive lists.
- **Actionability**: Brief next-step suggestions are sufficient. Do NOT require detailed how-to guides.
- **Clarity**: Conciseness IS a form of clarity. Short bullet points are ideal, not a weakness.
"""
        elif self.verbosity == 'medium':
            return """
## Verbosity Context: MEDIUM
The response was generated with VERBOSITY=MEDIUM. Moderate detail is expected.
Score normally but don't require exhaustive coverage of every sub-topic.
"""
        return ""  # 'high' or None — no special context needed
    
    def _init_openai_service(self) -> OpenAIService:
        """Initialize OpenAI service from environment."""
        return OpenAIService(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_KEY") or os.getenv("OPENAI_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            deployment_name=os.getenv("CHAT_DEPLOYMENT", "gpt-4o")
        )
    
    def _evaluate_dimensions(self,query_id:int, query: str, response: str, context: List[str]) -> tuple[Dict[str, Any], Dict[str, int]]:
        """
        Evaluate response across all 6 RADAR dimensions.
        
        Returns tuple of (evaluation_dict, usage_dict) where usage contains prompt_tokens and completion_tokens.
        """
        context_str = "\n---\n".join(context) if isinstance(context, list) else context
        
        prompt = f"""You are an objective quality evaluator for a RAG (Retrieval-Augmented Generation) system.

IMPORTANT: This is a QUALITY evaluation, not a TRUTH evaluation.
Truth verification (grounding, evidence support) is handled by a separate Groundedness system.
Your job is to evaluate stylistic quality, structure, and appropriateness.
{self._get_verbosity_eval_context()}
Evaluate this response across 6 quality dimensions on a 0.0-1.0 scale:

## Query
"{query}"

## Response to Evaluate
"{response[:2000]}"

## Source Context
{context_str[:5000]}

## Dimensions to Score

1. **Query Resolution** (0.0-1.0): Does the response directly address and answer the user's question?
   - 1.0 = Directly and completely addresses the query
   - 0.5 = Partially addresses, missing key aspects
   - 0.0 = Does not address the query at all

2. **Scope Discipline** (0.0-1.0): Does the answer avoid unnecessary or overconfident claims beyond what is needed?
   - 1.0 = Appropriately scoped, no overclaiming or overconfidence
   - 0.5 = Some overreach or unnecessary certainty
   - 0.0 = Significant overclaiming or overconfidence
   
   NOTE: Do NOT judge whether claims are supported by sources (that's Groundedness' job).
   Only evaluate whether the response avoids going beyond what is needed to answer the question.

3. **Completeness** (0.0-1.0): Is the response thorough with necessary steps, details, and caveats?
   - 1.0 = Comprehensive, covers all important aspects
   - 0.5 = Basic coverage, missing some details
   - 0.0 = Incomplete or superficial
   
   NOTE: Saying "I couldn't find information about X" or "This requires escalation" is NOT a completeness failure.

4. **Clarity** (0.0-1.0): Is the response well-organized and easy to understand?
   - 1.0 = Crystal clear, well-structured
   - 0.5 = Understandable but could be clearer
   - 0.0 = Confusing or poorly organized

5. **Actionability** (0.0-1.0): Does it provide concrete, actionable next steps (if applicable)?
   - 1.0 = Highly actionable with clear steps
   - 0.5 = Some guidance but lacks specificity
   - 0.0 = No actionable content (if expected)

6. **Citation Hygiene** (0.0-1.0): Are citation markers syntactically correct and valid?
   - 1.0 = All [n] references are syntactically correct and match source IDs
   - 0.5 = Some formatting issues or dangling citations
   - 0.0 = Invalid citation syntax or fake citations
   
   NOTE: Do NOT judge whether citations support claims (that's Groundedness' job).
   Only evaluate formatting and syntactic correctness.

Respond with JSON only:
{{
    "query_resolution": {{"score": 0.0-1.0, "reason": "brief explanation"}},
    "scope_discipline": {{"score": 0.0-1.0, "reason": "explanation", "overreach_examples": ["examples of overclaiming if any"]}},
    "completeness": {{"score": 0.0-1.0, "reason": "explanation", "missing": ["list of missing aspects"]}},
    "clarity": {{"score": 0.0-1.0, "reason": "explanation"}},
    "actionability": {{"score": 0.0-1.0, "reason": "explanation"}},
    "citation_hygiene": {{"score": 0.0-1.0, "reason": "explanation", "formatting_issues": ["list of formatting issues"]}}
}}
"""
        
        try:
            content, usage = self.openai_service.get_chat_response(
                messages=[
                    {"role": "system", "content": "You are an evaluation judge. Output valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=1500,
                response_format={"type": "json_object"},
                return_usage=True,
                query_id=query_id,
                scenario="radar_correction_evaluation"
            )
            
            return json.loads(content), usage
        except Exception as e:
            logger.error(f"RADAR evaluation failed: {e}")
            # Return neutral scores on error
            return (
                {dim: {"score": 0.5, "reason": f"Evaluation error: {e}"} 
                 for dim in self.DEFAULT_THRESHOLDS.keys()},
                {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            )
    
    def _identify_failing_dimensions(self, evaluation: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Identify dimensions below their thresholds.
        
        Returns list of dicts with dimension info for failing dimensions.
        """
        failing = []
        
        for dim_name, threshold in self.thresholds.items():
            dim_result = evaluation.get(dim_name, {})
            score = dim_result.get("score", 0.5)
            
            if score < threshold:
                failing.append({
                    "name": dim_name,
                    "score": score,
                    "threshold": threshold,
                    "reason": dim_result.get("reason", ""),
                    "details": dim_result  # Full details for prompt building
                })
        
        return failing
    
    def _build_dimension_feedback(self, failing_dimensions: List[Dict[str, Any]], query: str) -> str:
        """Build human-readable feedback for each failing dimension."""
        feedback_parts = []
        
        for dim in failing_dimensions:
            dim_name = dim["name"]
            template = self.DIMENSION_FEEDBACK.get(dim_name, "**{name}**: Score {score:.0%} - {reason}")
            
            # Build details string based on dimension type
            details = dim.get("details", {})
            details_str = ""
            
            if dim_name == "scope_discipline":
                overreach = details.get("overreach_examples", [])
                if overreach:
                    details_str = "\n".join(f"- {ex}" for ex in overreach[:5])
                else:
                    details_str = "Reduce overclaiming and overconfidence."
            elif dim_name == "completeness":
                missing = details.get("missing", [])
                if missing:
                    details_str = "\n".join(f"- {item}" for item in missing[:5])
                else:
                    details_str = "Add more depth and coverage."
            elif dim_name == "citation_hygiene":
                issues = details.get("formatting_issues", [])
                if issues:
                    details_str = "\n".join(f"- {issue}" for issue in issues[:5])
                else:
                    details_str = "Fix citation formatting and syntax."
            
            feedback = template.format(
                score=dim["score"],
                query=query,
                details=details_str or dim.get("reason", "Needs improvement")
            )
            feedback_parts.append(feedback)
        
        return "\n\n".join(feedback_parts)
    
    def _build_dimension_instructions(self, failing_dimensions: List[Dict[str, Any]]) -> str:
        """Build specific instructions based on failing dimensions."""
        instructions = []
        
        for dim in failing_dimensions:
            dim_name = dim["name"]
            
            if dim_name == "scope_discipline":
                instructions.append("""**For Scope Discipline:**
- Soften overconfident language without deleting claims
- Add hedging: "Based on the documentation..." or "Typically..."
- Narrow scope: "For the specific case of X..." instead of universal claims
- Do NOT remove claims that Groundedness has allowed—just adjust certainty
""")
            elif dim_name == "query_resolution":
                instructions.append("""**For Query Resolution:**
- Lead with a direct answer to the question
- Don't bury the key point in explanations
- If you can't fully answer, say so upfront then provide what you can
""")
            elif dim_name == "completeness":
                instructions.append("""**For Completeness:**
- Add any missing steps or details
- Include relevant caveats or edge cases
- Cover the "what next?" if helpful
- Note: "I couldn't find information about X" is a valid answer, not a failure
""")
            elif dim_name == "clarity":
                instructions.append("""**For Clarity:**
- Use bullet points or numbered lists for steps
- Add section headers if the response is long
- Define technical terms briefly
""")
            elif dim_name == "actionability":
                instructions.append("""**For Actionability:**
- End with clear "Next Steps" or "To Do"
- Be specific about what to click, where to go, what to do
""")
            elif dim_name == "citation_hygiene":
                instructions.append("""**For Citation Hygiene:**
- Fix citation syntax: ensure [n] format is used consistently
- Remove dangling citations (numbers with no matching source)
- Ensure citation numbers reference actual source IDs from context
- Do NOT add or remove citations based on claim support—just fix formatting
""")
        
        return "\n".join(instructions)
    
    def _build_correction_prompt(
        self,
        draft: str,
        query: str,
        context: str,
        failing_dimensions: List[Dict[str, Any]]
    ) -> str:
        """Build the warm correction prompt from evaluation results."""
        dimension_feedback = self._build_dimension_feedback(failing_dimensions, query)
        dimension_instructions = self._build_dimension_instructions(failing_dimensions)
        
        # Inject verbosity constraint into the prompt
        verbosity_instruction = self.VERBOSITY_INSTRUCTIONS.get(
            self.verbosity or 'medium', ''
        )
        
        return self.WARM_CORRECTION_PROMPT.format(
            query=query,
            draft=draft,
            context=context[:8000],  # Limit context size
            dimension_feedback=dimension_feedback,
            dimension_instructions=dimension_instructions,
            verbosity_instruction=verbosity_instruction
        )
    
    def _apply_correction(self,query_id:int, correction_prompt: str) -> tuple[Optional[str], Dict[str, int]]:
        """Send correction prompt to LLM and return (corrected_response, usage_dict).
        
        Uses Responses API when self.use_responses_api is True, which properly
        applies the persona's verbosity and reasoning_effort constraints.
        Falls back to Chat Completions on error.
        """
        if self.use_responses_api:
            try:
                logger.info(f"[RADAR] Correction via Responses API (verbosity={self.verbosity}, reasoning={self.reasoning_effort})")
                content, usage = self.openai_service.get_responses_api_response(
                    messages=[{"role": "user", "content": correction_prompt}],
                    reasoning_effort=self.reasoning_effort or 'medium',
                    verbosity=self.verbosity or 'medium',
                    max_tokens=2000,
                    return_usage=True,
                    query_id=query_id,
                    scenario="radar_correction_apply",
                    api_version=self.responses_api_version,
                )
                return content, usage
            except Exception as e:
                logger.warning(f"[RADAR] Responses API correction failed, falling back to Chat Completions: {e}")
                # Fall through to Chat Completions below
        
        try:
            content, usage = self.openai_service.get_chat_response(
                messages=[{"role": "user", "content": correction_prompt}],
                max_tokens=2000,
                temperature=self.temperature,  # Higher temp for natural flow (0.6)
                return_usage=True,
                query_id=query_id,
                scenario="radar_correction_apply"
            )
            return content, usage
        except Exception as e:
            logger.error(f"Correction LLM call failed: {e}")
            return None, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    def evaluate_only(self, draft: str, query_id:int ,query: str, context: Union[List[str], str]) -> RadarCorrectionResult:
        """
        Evaluate a response with RADAR dimensions WITHOUT applying corrections.
        Used for streaming responses where correction isn't possible.
        
        Args:
            draft: The response to evaluate
            query_id: The id of the query
            query: The original question
            context: The source context (list of chunks or string)
            
        Returns:
            RadarCorrectionResult with evaluation data only (was_corrected=False)
        """
        # Normalize context to list
        context_list = context if isinstance(context, list) else [context]
        
        # Evaluate only, no correction loop
        logger.info("RADAR evaluate_only: scoring response without correction")
        evaluation, eval_usage = self._evaluate_dimensions(query_id,query, draft, context_list)
        
        # Extract scores and reasons
        radar_scores = {dim: evaluation.get(dim, {}).get("score", 0.5) 
                      for dim in self.DEFAULT_THRESHOLDS.keys()}
        radar_reasons = {dim: evaluation.get(dim, {}).get("reason", "") 
                       for dim in self.DEFAULT_THRESHOLDS.keys()}
        
        # Identify failing dimensions (for reference only)
        failing_dimensions = self._identify_failing_dimensions(evaluation)
        failing_names = [d["name"] for d in failing_dimensions]
        
        logger.info(f"RADAR evaluate_only scores: {radar_scores}, tokens: {eval_usage}")
        
        return RadarCorrectionResult(
            final_response=draft,  # Unchanged
            was_corrected=False,   # Never corrected in evaluate_only
            original_draft=draft,  # Same as final
            radar_scores=radar_scores,
            radar_reasons=radar_reasons,
            failing_dimensions=failing_names,
            correction_prompt=None,
            rounds_used=0,
            eval_prompt_tokens=eval_usage.get("prompt_tokens", 0),
            eval_completion_tokens=eval_usage.get("completion_tokens", 0),
            correction_prompt_tokens=0,
            correction_completion_tokens=0
        )

    def correct_response(
        self,
        draft: str,
        query_id : int,
        query: str,
        context: List[str] | str,
        max_rounds: Optional[int] = None,
        thresholds: Optional[Dict[str, float]] = None
    ) -> RadarCorrectionResult:
        """
        Evaluate a draft response and apply RADAR-guided corrections if needed.
        
        Args:
            draft: The draft response to evaluate
            query: The original question
            context: The source context (list of chunks or string)
            max_rounds: Maximum correction attempts (overrides instance setting)
            thresholds: Per-dimension thresholds (overrides instance setting)
        
        Returns:
            RadarCorrectionResult with final response and metadata
        """
        max_rounds = max_rounds or self.max_rounds
        thresholds = thresholds or self.thresholds
        
        # Normalize context to list
        context_list = context if isinstance(context, list) else [context]
        context_str = "\n---\n".join(context_list)
        
        current_response = draft
        rounds_used = 0
        correction_prompt = None
        was_corrected = False
        radar_scores = {}
        radar_reasons = {}  # Store per-dimension reasoning for logging
        failing_names = []
        
        # Token tracking
        total_eval_prompt_tokens = 0
        total_eval_completion_tokens = 0
        total_correction_prompt_tokens = 0
        total_correction_completion_tokens = 0
        
        for round_num in range(max_rounds):
            # Evaluate current response with RADAR
            logger.info(f"RADAR evaluation round {round_num + 1}")
            evaluation, eval_usage = self._evaluate_dimensions(query_id,query, current_response, context_list)
            
            # Accumulate eval tokens
            total_eval_prompt_tokens += eval_usage.get("prompt_tokens", 0)
            total_eval_completion_tokens += eval_usage.get("completion_tokens", 0)
            
            # Extract scores and reasons for logging
            radar_scores = {dim: evaluation.get(dim, {}).get("score", 0.5) 
                          for dim in self.DEFAULT_THRESHOLDS.keys()}
            radar_reasons = {dim: evaluation.get(dim, {}).get("reason", "") 
                           for dim in self.DEFAULT_THRESHOLDS.keys()}
            
            logger.info(f"RADAR scores: {radar_scores}")
            
            # Identify failing dimensions
            failing_dimensions = self._identify_failing_dimensions(evaluation)
            failing_names = [d["name"] for d in failing_dimensions]
            
            if not failing_dimensions:
                logger.info("All dimensions pass thresholds, no correction needed")
                break
            
            logger.info(f"Failing dimensions: {failing_names}")
            
            # Build correction prompt
            correction_prompt = self._build_correction_prompt(
                draft=current_response,
                query=query,
                context=context_str,
                failing_dimensions=failing_dimensions
            )
            
            # Apply correction
            corrected, corr_usage = self._apply_correction(query_id,correction_prompt)
            
            # Accumulate correction tokens
            total_correction_prompt_tokens += corr_usage.get("prompt_tokens", 0)
            total_correction_completion_tokens += corr_usage.get("completion_tokens", 0)
            
            if corrected and corrected.strip():
                current_response = corrected
                was_corrected = True
                rounds_used = round_num + 1
                logger.info(f"RADAR correction applied in round {round_num + 1}")
            else:
                logger.warning("Correction returned empty response, keeping original")
                break
        
        total_tokens = (total_eval_prompt_tokens + total_eval_completion_tokens +
                       total_correction_prompt_tokens + total_correction_completion_tokens)
        logger.info(f"RADAR total tokens: {total_tokens} (eval: {total_eval_prompt_tokens + total_eval_completion_tokens}, correction: {total_correction_prompt_tokens + total_correction_completion_tokens})")
        
        return RadarCorrectionResult(
            final_response=current_response,
            was_corrected=was_corrected,
            original_draft=draft,
            radar_scores=radar_scores,
            radar_reasons=radar_reasons,
            failing_dimensions=failing_names,
            correction_prompt=correction_prompt if was_corrected else None,
            rounds_used=rounds_used,
            eval_prompt_tokens=total_eval_prompt_tokens,
            eval_completion_tokens=total_eval_completion_tokens,
            correction_prompt_tokens=total_correction_prompt_tokens,
            correction_completion_tokens=total_correction_completion_tokens
        )

    @classmethod
    def from_env(
        cls,
        use_responses_api: bool = False,
        verbosity: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        responses_api_version: str = '2025-03-01-preview',
    ) -> 'RadarCorrectionLoop':
        """Create RadarCorrectionLoop from environment variables."""
        return cls(
            use_responses_api=use_responses_api,
            verbosity=verbosity,
            reasoning_effort=reasoning_effort,
            responses_api_version=responses_api_version,
        )
