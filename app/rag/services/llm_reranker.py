"""
LLM-based Reranker Service with Cosine Similarity and LLM modes.

Provides non-blocking reranking of search results with graceful fallback.
"""
import json
import logging
import math
from typing import List, Dict, Optional, Any

from app.utils.config_resolver import get_resolver

logger = logging.getLogger(__name__)


class LLMReranker:
    """
    Non-blocking reranker with cosine similarity and LLM scoring modes.
    
    Modes:
        - cosine: Fast reranking using cosine similarity (no API calls)
        - llm: LLM-based 1-10 relevance scoring
        - hybrid: Cosine first, LLM on close scores
    """
    
    def __init__(
        self,
        openai_service: Any = None,
        enabled: bool = False,
        mode: str = "cosine",
        model: str = None
    ):
        """
        Initialize the reranker.
        
        Args:
            openai_service: Optional OpenAI service instance for LLM mode
            enabled: Whether reranking is enabled
            mode: Reranking mode - 'cosine', 'llm', or 'hybrid'
            model: Custom model for reranking (uses default if None)
        """
        self.openai_service = openai_service
        self.enabled = enabled
        self.mode = mode.lower()
        self.model = model  # Custom model for reranking (uses default if None)
        
        logger.info(f"LLMReranker initialized: enabled={self.enabled}, mode={self.mode}, model={self.model or 'default'}")
    @staticmethod
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(y * y for y in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)
    
    def rerank(
        self,
        query: str,
        query_id: int,
        query_embedding: Optional[List[float]],
        documents: List[Dict],
        top_k: int = 5
    ) -> List[Dict]:
        """
        Rerank documents based on relevance to query.
        
        Non-blocking: Returns original order on any failure.
        
        Args:
            query: The user's search query
            query_embedding: Embedding vector for the query (required for cosine mode)
            documents: List of document dicts with 'chunk', 'title', etc.
            top_k: Number of top results to return
            
        Returns:
            Reranked list of documents (best first), or original order on failure
        """
        if not self.enabled:
            return documents[:top_k] if documents else []
        
        if not documents:
            return []
        
        try:
            if self.mode == "cosine":
                return self._cosine_rerank(query_embedding, documents, top_k)
            elif self.mode == "llm":
                return self._llm_rerank(query, query_id,documents, top_k)
            elif self.mode == "hybrid":
                return self._hybrid_rerank(query, query_embedding, documents, top_k)
            else:
                logger.warning(f"Unknown reranker mode '{self.mode}', returning original order")
                return documents[:top_k]
        except Exception as e:
            logger.warning(f"Reranking failed, returning original order: {e}")
            return documents[:top_k]
    
    def _cosine_rerank(
        self,
        query_embedding: Optional[List[float]],
        documents: List[Dict],
        top_k: int
    ) -> List[Dict]:
        """
        Fast cosine similarity reranking.
        
        Requires documents to have 'embedding' field or falls back to original order.
        """
        if not query_embedding:
            logger.warning("No query embedding provided for cosine rerank, returning original order")
            return documents[:top_k]
        
        scored_docs = []
        for doc in documents:
            doc_embedding = doc.get("embedding")
            if doc_embedding:
                score = self.cosine_similarity(query_embedding, doc_embedding)
            else:
                # If no embedding, use existing relevance score or default
                score = doc.get("relevance", 0.5)
            scored_docs.append((score, doc))
        
        # Sort by score descending
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        
        reranked = []
        for score, doc in scored_docs[:top_k]:
            doc['relevance'] = score
            reranked.append(doc)
            
        logger.info(f"Cosine rerank: reordered {len(documents)} docs to top {len(reranked)}")
        return reranked
    
    def _llm_rerank(self, query: str,query_id, documents: List[Dict], top_k: int) -> List[Dict]:
        """
        LLM-based relevance scoring (1-10 scale).
        
        Uses existing OpenAI service to score document relevance.
        """
        if not self.openai_service:
            logger.warning("No OpenAI service for LLM rerank, returning original order")
            return documents[:top_k]
        
        # Build scoring prompt
        prompt = self._build_scoring_prompt(query, documents)
        
        messages = [
            {"role": "system", "content": "You are a relevance scoring assistant. Respond only with valid JSON."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = self.openai_service.get_chat_response(
                messages=messages,
                temperature=0.1,
                max_tokens=200,
                scenario = "llm_reranker",
                query_id = query_id,
                model=self.model  # Use custom reranker model if specified
            )
            
            scores = self._parse_scores(response, len(documents))
            
            # Pair scores with documents
            scored_docs = list(zip(scores, documents))
            scored_docs.sort(key=lambda x: x[0], reverse=True)
            
            reranked = []
            for score, doc in scored_docs[:top_k]:
                doc['relevance'] = score
                reranked.append(doc)
                
            logger.info(f"LLM rerank: reordered {len(documents)} docs to top {len(reranked)}")
            return reranked
            
        except Exception as e:
            logger.warning(f"LLM rerank failed: {e}, returning original order")
            return documents[:top_k]
    
    def _hybrid_rerank(
        self,
        query: str,
        query_embedding: Optional[List[float]],
        documents: List[Dict],
        top_k: int
    ) -> List[Dict]:
        """
        Hybrid reranking: cosine first, then LLM on close scores.
        
        Uses cosine similarity for initial ranking, then applies LLM 
        reranking to documents with similar scores (within threshold).
        """
        # First pass: cosine similarity
        cosine_results = self._cosine_rerank(query_embedding, documents, min(top_k * 2, len(documents)))
        
        # If no LLM service or few results, return cosine results
        if not self.openai_service or len(cosine_results) <= 3:
            return cosine_results[:top_k]
        
        # Second pass: LLM rerank top candidates
        llm_candidates = cosine_results[:min(top_k + 2, len(cosine_results))]
        return self._llm_rerank(query, llm_candidates, top_k)
    
    def _build_scoring_prompt(self, query: str, documents: List[Dict]) -> str:
        """Build the prompt for LLM relevance scoring."""
        doc_summaries = []
        for i, doc in enumerate(documents, 1):
            title = doc.get("title", "Untitled")
            chunk = doc.get("chunk", "")[:300]  # Limit chunk preview
            doc_summaries.append(f"[{i}] Title: {title}\n{chunk}")
        
        docs_text = "\n\n".join(doc_summaries)
        
        return f"""Score each document's relevance to the query on a scale of 1-10.

Query: "{query}"

Documents:
{docs_text}

Respond with ONLY a JSON object mapping document numbers to scores:
{{"1": 8, "2": 3, "3": 9}}

Scoring:
- 9-10: Directly answers the query
- 7-8: Highly relevant
- 5-6: Somewhat relevant
- 3-4: Minimally relevant
- 1-2: Not relevant"""
    
    def _parse_scores(self, response: str, num_docs: int) -> List[float]:
        """Parse LLM response into list of scores."""
        try:
            # Extract JSON from response (handle markdown code blocks)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            
            scores_dict = json.loads(response)
            
            # Convert to ordered list
            scores = []
            for i in range(1, num_docs + 1):
                score = scores_dict.get(str(i), scores_dict.get(i, 5))  # Default to 5
                scores.append(float(score))
            
            return scores
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse LLM scores: {e}")
            # Return neutral scores
            return [5.0] * num_docs
    
    def is_available(self) -> bool:
        """Check if reranker is available and enabled."""
        if not self.enabled:
            return False
        if self.mode in ("llm", "hybrid") and not self.openai_service:
            return False
        return True


def log_feature_configuration():
    """Log current feature configuration at startup."""
    
    resolver = get_resolver()
    reranker_enabled_str, _ = resolver.get("ENABLE_RERANKER", default="false")
    reranker_enabled = reranker_enabled_str.lower() == "true"
    reranker_mode, _ = resolver.get("RERANKER_MODE", default="cosine")
    reranker_model, _ = resolver.get("RERANKER_MODEL", default=None)
    clarifier_enabled_str, _ = resolver.get("ENABLE_CLARIFIER", default="false")
    clarifier_enabled = clarifier_enabled_str.lower() == "true"
    
    model_info = f", model: {reranker_model}" if reranker_model else ""
    logger.info("=" * 50)
    logger.info("=== Feature Configuration ===")
    logger.info(f"  Reranker: {'ENABLED' if reranker_enabled else 'DISABLED'} (mode: {reranker_mode}{model_info})")
    logger.info(f"  Clarifier: {'ENABLED' if clarifier_enabled else 'DISABLED'}")
    logger.info("=" * 50)

