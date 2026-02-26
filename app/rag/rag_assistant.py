import logging
import os
import re
import threading
import time
import traceback
from typing import List, Dict, Tuple, Optional, Any, Generator, Union

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

from app.Connection import get_connection
from app.models.models import Queries, QueryDetails, OpenAIUsage, SelfCritiqueMetrics
from app.rag.conversation_manager import ConversationManager
from app.rag.openai_service import OpenAIService
from app.rag.services.groundedness_checker import GroundednessChecker
from app.rag.services.llm_reranker import LLMReranker, log_feature_configuration
from app.rag.services.radar_correction_loop import RadarCorrectionLoop
from app.utils.app_util import _get_user_id
from app.utils.config_resolver import ConfigResolver
from app.utils.mode_config import get_persona_config, get_persona, get_setting_of_persona, get_mode, \
    ADVANCED_SELF_CRITIQUE_PROMPT_TEMPLATE, get_reasoning_effort, get_verbosity
from app.utils.openai_logger import log_openai_call
from app.utils.runtime_config_checker import run_config_check, log_config_summary

# Import config but handle the case where it might import streamlit
try:
    from config import (
        OPENAI_ENDPOINT,
        OPENAI_KEY,
        OPENAI_API_VERSION,
        EMBEDDING_DEPLOYMENT,
        CHAT_DEPLOYMENT,
        SEARCH_ENDPOINT,
        SEARCH_INDEX,
        SEARCH_KEY,
        VECTOR_FIELD, get_cost_rates,
)
except ImportError as e:
    if 'streamlit' in str(e):
        # Define fallback values or load from environment
        OPENAI_ENDPOINT = os.environ.get("OPENAI_ENDPOINT")
        OPENAI_KEY = os.environ.get("OPENAI_KEY")
        OPENAI_API_VERSION = os.environ.get("OPENAI_API_VERSION")
        EMBEDDING_DEPLOYMENT = os.environ.get("EMBEDDING_DEPLOYMENT")
        CHAT_DEPLOYMENT = os.environ.get("CHAT_DEPLOYMENT")
        SEARCH_ENDPOINT = os.environ.get("SEARCH_ENDPOINT")
        SEARCH_INDEX = os.environ.get("SEARCH_INDEX")
        SEARCH_KEY = os.environ.get("SEARCH_KEY")
        VECTOR_FIELD = os.environ.get("VECTOR_FIELD")
    else:
        raise

logger = logging.getLogger(__name__)


class FactCheckerStub:
    """No-op evaluator so we still return a dict in the tuple."""
    def evaluate_response(
        self, query: str, answer: str, context: str, deployment: str
    ) -> Dict[str, Any]:
        return {}


def format_context_text(text: str) -> str:
    # Add line breaks after long sentences
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    formatted = "\n\n".join(sentence for sentence in sentences if sentence)
    
    # Optional: emphasize headings or keywords
    formatted = re.sub(r'(?<=\n\n)([A-Z][^\n:]{5,40})(?=\n\n)', r'**\1**', formatted)  # crude title detection
    
    return formatted

def dedupe_lines_preserve_order(text: str) -> str:
    """
    Remove duplicate lines while preserving order.
    - Collapses consecutive blank lines to a single blank line
    - Deduplicates exact repeated lines (useful for repeated URLs)
    """
    seen = set()
    out: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s == "":
            if out and out[-1].strip() == "":
                continue
            out.append("")
            continue
        if s not in seen:
            seen.add(s)
            out.append(line)
    return "\n".join(out)

def compress_adjacent_duplicate_citations(text: str) -> str:
    """
    Collapse immediately repeated inline citations like [1][1] or '[2] [2]' into a single occurrence.
    Only affects adjacent duplicates separated by optional whitespace (including newlines).
    """
    # Collapse exact adjacent duplicates (including across whitespace/newlines)
    text = re.sub(r'(\[\d+\])(\s*\1)+', r'\1', text)
    return text

def dedupe_sources_by_key(sources: List[Dict], content_field: str = "content") -> List[Dict]:
    """
    Dedupe sources by parent_id when available, keeping the highest-scoring chunk.
    Fallback key: title + first 200 chars of the specified content field.
    """
    best_by_key = {}
    
    for src in sources:
        pid = src.get("parent_id", "") or ""
        # Use the specified content field for the fallback key
        content_for_key = src.get(content_field, "") or ""
        key = pid if pid else f"{src.get('title', '')}|{content_for_key[:200]}"
        
        # Get score, defaulting to 0 if not present
        score = src.get("relevance", 0)
        
        # If this is the first time we see this key, or if this chunk has a higher score
        # than the one we've stored, keep this one
        if key not in best_by_key or score > best_by_key[key].get("relevance", 0):
            best_by_key[key] = src
            
    # Convert back to list and sort by relevance descending to keep best chunks first
    deduped = list(best_by_key.values())
    deduped.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    
    if len(deduped) != len(sources):
        try:
            logger.info(f"Dedupe sources by key reduced from {len(sources)} to {len(deduped)}")
        except Exception:
            pass
    return deduped

class FlaskRAGAssistantWithHistory:
    """Retrieval-Augmented Generation assistant with in-memory conversation history."""

    # Default system prompt
    DEFAULT_SYSTEM_PROMPT = """
    ### Task:

    Respond to the user query using the provided context, incorporating inline citations in the format [id] **only when the <source> tag includes an explicit id attribute** (e.g., <source id="1">).
    
    ### Guidelines:

    - If you don't know the answer, clearly state that.
    - If uncertain, ask the user for clarification.
    - Respond in the same language as the user's query.
    - If the context is unreadable or of poor quality, inform the user and provide the best possible answer.
    - **Only include inline citations using [id] (e.g., [1], [2]) when the <source> tag includes an id attribute.**
    - Do not cite if the <source> tag does not contain an id attribute.
    - Do not use XML tags in your response.
    - Ensure citations are concise and directly related to the information provided.
    - Maintain continuity with previous conversation by referencing earlier exchanges when appropriate.
    - **IMPORTANT: For follow-up questions, continue to use citations [id] when referencing information from the provided context, even if you've mentioned this information in previous responses.**


























- **Always cite your sources in every response, including follow-up questions.**
+    - Citations are mandatory ONLY for information strictly derived from the context.
+    - If the context does not contain the answer, state that you cannot find the information in the provided sources. DO NOT fabricate a citation.
    
    ### Example of Citation:

    If the user asks about a specific topic and the information is found in a source with a provided id attribute, the response should include the citation like in the following example:

    * "According to the study, the proposed method increases efficiency by 20% [1]."
    
    ### Follow-up Questions:
    
    For follow-up questions, you must continue to cite sources. For example:
    
    User: "What are the key features of Product X?"
    Assistant: "Product X has three main features: cloud integration [1], advanced analytics [2], and mobile support [3]."
    
    User: "Tell me more about the mobile support."
    Assistant: "The mobile support feature of Product X includes cross-platform compatibility, offline mode, and push notifications [3]."
    
    ### Output:

    Provide a clear and direct response to the user's query, including inline citations in the format [id] only when the <source> tag with id attribute is present in the context. Remember to include citations in ALL responses, including follow-up questions.
    
    <context>

    {{CONTEXT}}
    </context>
    
    <user_query>

    {{QUERY}}
    </user_query>
    """

    # ───────────────────────── setup ─────────────────────────
    def __init__(self, settings=None) -> None:
        self._init_cfg()
        
        # Deployment name is now set from environment variable via config resolver
        # No hardcoded enforcement - respects AZURE_OPENAI_MODEL or CHAT_DEPLOYMENT from .env
        logger.info(f"Using chat deployment: {self.deployment_name}")
        # Initialize the OpenAI service
        self.openai_service = OpenAIService(
            azure_endpoint=self.openai_endpoint,
            api_key=self.openai_key,
            api_version=self.openai_api_version or "2024-08-01-preview",
            deployment_name=self.deployment_name
        )
        
        # Initialize the conversation manager with the system prompt
        self.conversation_manager = ConversationManager(self.DEFAULT_SYSTEM_PROMPT)
        
        try:
            self.fact_checker = GroundednessChecker.from_env()
        except Exception as e:
            logger.warning(f"Failed to initialize GroundednessChecker: {e}")
            self.fact_checker = FactCheckerStub()
        
        # Model parameters with defaults
        self.temperature = 0.3
        self.top_p = 1.0
        self.max_tokens = int(os.getenv('MAX_TOKENS', '1000'))
        self.presence_penalty = 0.6
        self.frequency_penalty = 0.6
        
        # Conversation history window size (in turns)
        self.max_history_turns = 5
        
        # Flag to track if history was trimmed in the most recent request
        self._history_trimmed = False
        
        # Summarization settings
        self.summarization_settings = {
            "enabled": True,                # Whether to use summarization (vs. simple truncation)
            "max_summary_tokens": 800,      # Maximum length of summaries
            "summary_temperature": 0.3,     # Temperature for summary generation
        }
        
        # Load settings if provided
        self.settings = settings or {}
        self._load_settings()
        
        # Initialize reranker (disabled by default)
        reranker_enabled_str, _ = self._config_resolver.get("ENABLE_RERANKER", default="false")
        reranker_enabled = reranker_enabled_str.lower() == "true"
        reranker_mode, _ = self._config_resolver.get("RERANKER_MODE", default="cosine")
        reranker_model, _ = self._config_resolver.get("RERANKER_MODEL", default=None)
        self.reranker = LLMReranker(
            openai_service=self.openai_service,
            enabled=reranker_enabled,
            mode=reranker_mode,
            model=reranker_model
        )
        
        # Log feature configuration at startup
        log_feature_configuration()
        
        # Run runtime config check (after all config is resolved)
        try:
            log_config_summary(self._config_resolver)
            run_config_check(self._config_resolver)
        except SystemExit:
            raise  # Re-raise if strict mode triggered
        except Exception as e:
            logger.warning(f"Runtime config check failed: {e}")
        
        logger.info("FlaskRAGAssistantWithHistory initialized with conversation history")

    def _init_cfg(self) -> None:
        # Initialize config resolver for tracking sources
        self._config_resolver = ConfigResolver()
        resolver = self._config_resolver
        
        # Resolve config with source tracking
        self.openai_endpoint, _ = resolver.get("OPENAI_ENDPOINT", fallback_keys=["AZURE_OPENAI_ENDPOINT"])
        self.openai_key, _ = resolver.get("OPENAI_KEY", fallback_keys=["AZURE_OPENAI_KEY"])
        self.openai_api_version, _ = resolver.get("OPENAI_API_VERSION", fallback_keys=["AZURE_OPENAI_API_VERSION"])
        self.embedding_deployment, _ = resolver.get("EMBEDDING_DEPLOYMENT", fallback_keys=["AZURE_OPENAI_EMBEDDING_NAME"])
        
        # CHAT_DEPLOYMENT has complex resolution: env -> fallback -> hardcoded override
        resolved_deployment, deployment_source = resolver.get(
            "CHAT_DEPLOYMENT", 
            fallback_keys=["AZURE_OPENAI_MODEL"]
        )
        self.deployment_name = resolved_deployment
        self._deployment_source = deployment_source  # Track for override registration
        
        self.search_endpoint, _ = resolver.get("SEARCH_ENDPOINT", fallback_keys=["AZURE_SEARCH_SERVICE"])
        self.search_index, _ = resolver.get("SEARCH_INDEX", fallback_keys=["AZURE_SEARCH_INDEX"])
        self.search_key, _ = resolver.get("SEARCH_KEY", fallback_keys=["AZURE_SEARCH_KEY"])
        self.vector_field, _ = resolver.get("VECTOR_FIELD")
        
    def _load_settings(self) -> None:
        """Load settings from provided settings dict"""
        settings = self.settings
        
        # Update model parameters
        if "model" in settings:
            requested_model = settings["model"]
            # Use the requested model instead of enforcing a specific one
            logger.info(f"Updating chat deployment to: {requested_model}")
            self.deployment_name = requested_model
            # Update the OpenAI service deployment name
            self.openai_service.deployment_name = self.deployment_name
            
        if "temperature" in settings:
            self.temperature = settings["temperature"]
        if "top_p" in settings:
            self.top_p = settings["top_p"]
        if "max_tokens" in settings:
            self.max_tokens = settings["max_tokens"]
        
        # Update search configuration
        if "search_index" in settings:
            self.search_index = settings["search_index"]
            
        # Update conversation history window size
        if "max_history_turns" in settings:
            self.max_history_turns = settings["max_history_turns"]
            logger.info(f"Setting max_history_turns to {self.max_history_turns}")
            
        # Update summarization settings
        if "summarization_settings" in settings:
            self.summarization_settings.update(settings.get("summarization_settings", {}))
            logger.info(f"Updated summarization settings: {self.summarization_settings}")
            

        # Update system prompt if provided
        # Check settings first (API override), then persona config
        system_prompt = settings.get("system_prompt")
        system_prompt_mode = settings.get("system_prompt_mode")
        
        # If not in settings, check persona config
        if not system_prompt:
            system_prompt = self.get_persona_setting("system_prompt")
            system_prompt_mode = self.get_persona_setting("system_prompt_mode", "Append")
            
        if system_prompt:
             # Default to Append if mode not specified
            if not system_prompt_mode:
                system_prompt_mode = "Append"
            
            logger.info(f"Applying system prompt with mode: {system_prompt_mode}")
            
            if system_prompt_mode == "Override":
                # Replace the default system prompt
                self.conversation_manager.clear_history(preserve_system_message=False)
                # Create the context placeholder exactly as the default prompt expects if needed, 
                # but since we are overriding, we assume the new prompt handles it or we append the placeholders.
                # However, the conversation manager logic for add_user_message inserts context into {{CONTEXT}} 
                # if it exists, but actually it constructs a new message.
                # The DEFAULT_SYSTEM_PROMPT has placeholders {{CONTEXT}} and {{QUERY}}. 
                # But in _chat_answer_with_history, we construct a context message:
                # context_message = f"<context>\n{context}\n</context>\n<user_query>\n{query}\n</user_query>"
                # So the system prompt doesn't strictly need the placeholders if it just gives instructions 
                # on how to handle the subsequent user/context message.
                
                self.conversation_manager.chat_history = [{"role": "system", "content": system_prompt}]
                logger.info(f"System prompt overridden with custom prompt")
            else:  # Append
                # Update the system message with combined prompt
                # Put custom prompt FIRST to establish persona/identity
                combined_prompt = f"{system_prompt}\n\n{self.DEFAULT_SYSTEM_PROMPT}"
                self.conversation_manager.clear_history(preserve_system_message=False)
                self.conversation_manager.chat_history = [{"role": "system", "content": combined_prompt}]
                logger.info(f"System prompt appended with custom prompt")

    # ───────────── embeddings ─────────────
    def generate_embedding(self, text: str, query_id: str, scenario: str) -> Optional[List[float]]:
        """Return embedding vector for text, or None if empty or on error."""
        if not text:
            return None
        
        try:
            # Use centralized OpenAI service for embeddings
            embedding = self.openai_service.get_embedding(
                text=text, 
                model=self.embedding_deployment
            )
            
            # Note: Usage logging for embeddings is now handled in get_embedding 
            # if we added it there, but for now we'll keep the direct log here 
            # if the service doesn't do it. 
            # Actually, I'll update the service to do logging for embeddings too if needed.
            
            return embedding
        except Exception as exc:
            logger.error(f"Embedding error: {exc}")
            return None

    @staticmethod
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        mag = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
        return 0.0 if mag == 0 else dot / mag

    # ───────────── Azure Search ───────────
    def search_knowledge_base(self, query: str, query_id: str) -> List[Dict]:
        """Vector search against Azure Cognitive Search; return top chunks with title and parent_id."""
        try:
            logger.info(f"Searching knowledge base for query: {query}")
            try:
                logger.debug(f"Query preview: {query[:120]} (len={len(query)})")
            except Exception:
                pass
            client = SearchClient(
                endpoint=self.search_endpoint,
                index_name=self.search_index,
                credential=AzureKeyCredential(self.search_key),
            )
            # Measure embedding generation time
            embed_start = time.time()
            q_vec = self.generate_embedding(query, query_id,'search_kb_query_embedding')
            embed_duration = int((time.time() - embed_start) * 1000)
            logger.info(f"Embedding generation took {embed_duration}ms")
            if not q_vec:
                logger.error("Failed to generate embedding for query")
                return []

            # Get persona-specific search parameters
            search_knn = self.get_persona_setting('search_knn', 10)
            search_top = self.get_persona_setting('search_top', 10)
            current_persona = get_persona()
            logger.info(f"Persona '{current_persona}': Using search_knn={search_knn}, search_top={search_top}")

            logger.info(f"Executing vector search with fields: {self.vector_field}")
            vec_q = VectorizedQuery(
                vector=q_vec,
                k_nearest_neighbors=search_knn,  # Persona-aware setting
                fields=self.vector_field,
            )

            # Log the search parameters
            logger.info(f"Search parameters: index={self.search_index}, vector_field={self.vector_field}, top={search_top}")

            # Add parent_id to select fields
            search_start = time.time()
            results = client.search(
                search_text=query,
                vector_queries=[vec_q],
                select=["chunk", "title", "parent_id", self.vector_field],  # Added vector field for reranking
                top=search_top,  # Persona-aware setting
            )
            search_duration = int((time.time() - search_start) * 1000)
            logger.info(f"Azure Search query took {search_duration}ms")

            # Convert results to list and log count
            result_list = list(results)
            logger.info(f"Search returned {len(result_list)} results")

            # Debug log the first result if available
            if result_list and len(result_list) > 0:
                first_result = result_list[0]
                logger.debug(f"First result - title: {first_result.get('title', 'No title')}")
                logger.debug(f"First result - has parent_id: {'Yes' if 'parent_id' in first_result else 'No'}")
                if 'parent_id' in first_result:
                    logger.debug(
                        f"First result - parent_id: {first_result.get('parent_id')[:30]}..." if first_result.get(
                            'parent_id') else "None")

            return [
                {
                    "chunk": r.get("chunk", ""),
                    "title": r.get("title", "Untitled"),
                    "parent_id": r.get("parent_id", ""),  # Include parent_id
                    "relevance": r.get("@search.score", 1.0),  # Use actual search score
                    "embedding": r.get(self.vector_field),  # Include embedding
                }
                for r in result_list
            ]
        except Exception as exc:
            logger.error(f"Search error: {exc}", exc_info=True)
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    # ───────── context & citations ────────
    def summarize_history(self, messages_to_summarize: List[Dict], query_id) -> Dict:
        """
        Summarize a portion of conversation history while preserving key information.
        
        Args:
            messages_to_summarize: List of message dictionaries to summarize
            
        Returns:
            A single system message containing the summary
        """
        logger.info(f"Summarizing {len(messages_to_summarize)} messages")
        
        # Extract all citation references from the messages
        citation_pattern = r'\[(\d+)\]'
        all_citations = []
        for msg in messages_to_summarize:
            if msg['role'] == 'assistant':
                citations = re.findall(citation_pattern, msg['content'])
                all_citations.extend(citations)
        
        # Create a prompt that emphasizes preserving citations and product information
        prompt = """
        Summarize the following conversation while:
        1. Preserving ALL mentions of specific products, models, and technical details
        2. Maintaining ALL citation references [X] in their original form
        3. Keeping the key questions and answers
        4. Focusing on technical information rather than conversational elements
        
        Conversation to summarize:
        """
        
        for msg in messages_to_summarize:
            prompt += f"\n\n{msg['role'].upper()}: {msg['content']}"
        
        # If there are citations, add special instructions
        if all_citations:
            prompt += f"\n\nIMPORTANT: Make sure to preserve these citation references in your summary: {', '.join(['[' + c + ']' for c in all_citations])}"

        # Get summary from OpenAI with specific instructions
        summary_messages = [
            {"role": "system",
             "content": "You create concise summaries that preserve technical details, product information, and citation references exactly as they appear in the original text."},
            {"role": "user", "content": prompt}
        ]
        
        # Use the existing OpenAI service
        summary_response = self.openai_service.get_chat_response(
            messages=summary_messages,
            temperature=self.summarization_settings.get("summary_temperature", 0.3),
            max_tokens=self.summarization_settings.get("max_summary_tokens", 800),
            query_id=query_id,
            scenario='summarize'
        )
        
        logger.info(f"Generated summary of length {len(summary_response)}")
        return {"role": "system", "content": f"Previous conversation summary: {summary_response}"}

    def _trim_history(self, messages: List[Dict], query_id) -> Tuple[List[Dict], bool]:
        """
        Trim conversation history to the last N turns while preserving key information through summarization.
        
        Args:
            messages: List of message dictionaries
            
        Returns:
            Tuple of (trimmed_messages, was_trimmed)
        """
        logger.info(
            f"TRIM_DEBUG: Called with {len(messages)} messages. Cap is {self.max_history_turns * 2 + 1}"
        )
        
        dropped = False
        
        # If we're under the limit, no trimming needed
        if len(messages) <= self.max_history_turns * 2 + 1:  # +1 for system message
            self._history_trimmed = False
            logger.info(f"No trimming needed. History size: {len(messages)}, limit: {self.max_history_turns * 2 + 1}")
            return messages, dropped
        
        # Check if summarization is enabled
        if not self.summarization_settings.get("enabled", True):
            # Fall back to original trimming behavior
            dropped = True
            logger.info(f"Summarization disabled, using simple truncation")
            
            # Keep system message + last N pairs
            trimmed_messages = [messages[0]] + messages[-self.max_history_turns * 2:]

            # Log after trimming
            logger.info(f"After simple truncation: {len(trimmed_messages)} messages")
            self._history_trimmed = True
            
            return trimmed_messages, dropped
        
        # We need to trim with summarization
        dropped = True
        logger.info(
            f"History size ({len(messages)}) exceeds limit ({self.max_history_turns * 2 + 1}), trimming with summarization...")

        # Extract the system message (first message)
        system_message = messages[0]
        
        # Determine which messages to keep and which to summarize
        messages_to_keep = messages[-self.max_history_turns * 2:]  # Keep the most recent N turns
        messages_to_summarize = messages[1:-self.max_history_turns * 2]  # Summarize older messages (excluding system)

        # If there are messages to summarize, generate a summary
        if messages_to_summarize:
            logger.info(f"Summarizing {len(messages_to_summarize)} messages")
            summary_message = self.summarize_history(messages_to_summarize, query_id)

            # Construct the new message list: system message + summary + recent messages
            trimmed_messages = [system_message, summary_message] + messages_to_keep
        else:
            # If no messages to summarize, just keep system + recent
            trimmed_messages = [system_message] + messages_to_keep
        
        logger.info(f"After trimming with summarization: {len(trimmed_messages)} messages")
        self._history_trimmed = True
        
        return trimmed_messages, dropped
        
    def _prepare_context(self, results: List[Dict]) -> Tuple[str, Dict]:
        """Build <source id="..."> context and a source map; normalize/dedupe chunks."""
        logger.debug(f"_prepare_context input results count: {len(results)} snippet: {results[:3]}")
        logger.info(f"Preparing context from {len(results)} search results")

        # Get persona-specific max chunks
        max_chunks = self.get_persona_setting('max_context_chunks', 5)
        logger.info(f"Persona '{get_persona()}': Using max_context_chunks={max_chunks}")

        entries, src_map = [], {}
        sid = 1
        valid_chunks = 0

        for res in results[:max_chunks]:  # Use persona-specific chunk count
            chunk = res["chunk"].strip()
            if not chunk:
                logger.warning(f"Empty chunk found in result {sid}, skipping")
                continue

            # Detect mid-sentence truncation (heuristic)
            # If the chunk doesn't end with terminal punctuation, append ellipsis to signal incompleteness to the LLM
            if chunk and chunk[-1] not in ('.', '?', '!', '"', "'", ')', ']', '}', '”', '’'):
                chunk += "..."

            valid_chunks += 1
            formatted_chunk = format_context_text(chunk)
            formatted_chunk = dedupe_lines_preserve_order(formatted_chunk)

            # Log parent_id if available
            parent_id = res.get("parent_id", "")
            if parent_id:
                logger.info(f"Source {sid} has parent_id: {parent_id[:30]}..." if len(parent_id) > 30 else parent_id)
            else:
                logger.warning(f"Source {sid} missing parent_id")

            entries.append(f'<source id="{sid}">{formatted_chunk}</source>')
            src_map[str(sid)] = {
                "title": res["title"],
                "content": formatted_chunk,
                "parent_id": parent_id  # Include parent_id in source map
            }
            sid += 1

        context_str = "\n\n".join(entries)
        if valid_chunks == 0:
            logger.warning("No valid chunks found in _prepare_context, returning fallback context")
            context_str = "[No context available from knowledge base]"

        logger.info(f"Prepared context with {valid_chunks} valid chunks and {len(src_map)} sources")
        return context_str, src_map

    def _chat_answer_with_history(self, query: str, context: str, src_map: Dict, query_id) -> str:
        """Generate a response using the conversation history"""
        logger.info("Generating response with conversation history")
        
        # Check if custom prompt is available in settings
        settings = self.settings
        custom_prompt = settings.get("custom_prompt", "")
        
        # Apply custom prompt to query if available
        if custom_prompt:
            query = f"{custom_prompt}\n\n{query}"
            logger.info(f"Applied custom prompt to query: {custom_prompt[:100]}...")
        
        # Create a context message
        context_message = f"<context>\n{context}\n</context>\n<user_query>\n{query}\n</user_query>"
        
        # Check if the system message is still present in the conversation history
        # This ensures that even if the magic wand enhanced the query, we still have our citation instructions
        raw_messages = self.conversation_manager.get_history()
        if not raw_messages or raw_messages[0]["role"] != "system":
            logger.warning("System message not found in conversation history, restoring default")
            # Restore the system message with citation instructions
            self.conversation_manager.clear_history(preserve_system_message=False)
            self.conversation_manager.chat_history = [{"role": "system", "content": self.DEFAULT_SYSTEM_PROMPT}]
            logger.info("Restored default system prompt with citation instructions")
        
        # Add the user message to conversation history (only once)
        logger.info(f"Adding user message to conversation history")
        self.conversation_manager.add_user_message(context_message)
        
        # Get the complete conversation history
        raw_messages = self.conversation_manager.get_history()
        
        # Trim history if needed
        messages, trimmed = self._trim_history(raw_messages, query_id)
        if trimmed:
            # Add a system notification at the end of history
            messages.append({"role": "system", "content": f"[History trimmed to last {self.max_history_turns} turns]"})
        
        # Log the conversation history
        logger.info(f"Conversation history has {len(messages)} messages (trimmed: {trimmed})")
        for i, msg in enumerate(messages):
            logger.info(f"Message {i} - Role: {msg['role']}")
            if i < 3 or i >= len(messages) - 2:  # Log first 3 and last 2 messages
                logger.info(f"Content: {msg['content'][:100]}...")
        
        # Get response from OpenAI service
        import json
        
        # Get persona-specific settings, with session overrides taking priority
        reasoning_effort = get_reasoning_effort() or self.get_persona_setting('reasoning_effort', None)
        verbosity = get_verbosity() or self.get_persona_setting('verbosity', None)
        use_responses_api = self.get_persona_setting('use_responses_api', False)
        responses_api_version = self.get_persona_setting('responses_api_version', '2025-03-01-preview')
        
        current_persona = self.settings.get('persona', get_persona())
        
        if use_responses_api:
            # Use the Responses API (supports reasoning effort + verbosity natively)
            logger.info(f"[RESPONSES API] Persona '{current_persona}' using Responses API with reasoning={reasoning_effort}, verbosity={verbosity}")
            
            payload = {
                "model": self.deployment_name,
                "messages": messages,
                "reasoning_effort": reasoning_effort,
                "verbosity": verbosity,
                "api_version": responses_api_version
            }
            logger.info("========== OPENAI RAW PAYLOAD (RESPONSES API) ==========")
            logger.info(json.dumps(payload, indent=2))
            
            try:
                response = self.openai_service.get_responses_api_response(
                    messages=messages,
                    reasoning_effort=reasoning_effort or 'medium',
                    verbosity=verbosity or 'medium',
                    max_tokens=self.max_tokens,
                    return_usage=True,
                    query_id=query_id,
                    scenario='tune_response_based_on_history',
                    api_version=responses_api_version,
                )
                
                if isinstance(response, tuple):
                    answer, usage_info = response
                    prompt_tokens = usage_info.get('prompt_tokens')
                    completion_tokens = usage_info.get('completion_tokens')
                    total_tokens = usage_info.get('total_tokens')
                else:
                    answer = response
                    usage_info = {}
                    prompt_tokens = completion_tokens = total_tokens = None
                
            except Exception as e:
                logger.error(f"[RESPONSES API] Non-streaming error: {e}", exc_info=True)
                logger.warning("[RESPONSES API] Falling back to Chat Completions API")
                use_responses_api = False  # Trigger fallback below
        
        if not use_responses_api:
            # Fallback: Chat Completions API
            payload = {
                "model": self.deployment_name,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "presence_penalty": self.presence_penalty,
                "frequency_penalty": self.frequency_penalty,
                "reasoning_effort": reasoning_effort,
                "verbosity": verbosity
            }
            logger.info("========== OPENAI RAW PAYLOAD (CHAT COMPLETIONS) ==========")
            logger.info(json.dumps(payload, indent=2))
            response = self.openai_service.get_chat_response(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                top_p=self.top_p,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
                return_usage=True,
                query_id=query_id,
                scenario='tune_response_based_on_history'
            )
            
            if isinstance(response, tuple):
                answer, usage_info = response
                prompt_tokens = usage_info.get('prompt_tokens')
                completion_tokens = usage_info.get('completion_tokens')
                total_tokens = usage_info.get('total_tokens')
            else:
                answer = response
                usage_info = {}
                prompt_tokens = completion_tokens = total_tokens = None
        
        # Add the assistant's response to conversation history
        self.conversation_manager.add_assistant_message(answer)
        
        return answer, usage_info

    def _filter_cited(self, answer: str, src_map: Dict) -> List[Dict]:
        logger.debug(f"_filter_cited received answer snippet: {answer[:300]}")
        logger.debug(f"_filter_cited src_map keys: {list(src_map.keys())}")
        logger.info("Filtering cited sources from answer")
        cited_sources = []
        
        # First, check for explicit citations in the format [id]
        explicit_citations = []
        seen_citations = set()
        # Find all bracketed content containing numbers, commas, or spaces
        matches = re.findall(r'\[([\d,\s]+)\]', answer)
        for match in matches:
            # Split by comma to handle [1, 2]
            parts = [p.strip() for p in match.split(',')]
            for part in parts:
                if part.isdigit():
                    sid = part
                    if sid in src_map and sid not in seen_citations:
                            explicit_citations.append(sid)
                            seen_citations.add(sid)
                            logger.info(f"Source {sid} is explicitly cited in the answer")

        # Add explicitly cited sources
        for sid in explicit_citations:
            sinfo = src_map[sid]
            parent_id = sinfo.get("parent_id", "")
            if parent_id:
                logger.info(f"Source {sid} has parent_id: {parent_id[:30]}..." if len(parent_id) > 30 else parent_id)
            else:
                logger.warning(f"Cited source {sid} missing parent_id")
            
            cited_source = {
                "id": sid,
                "title": sinfo["title"],
                "content": sinfo["content"],
                "parent_id": parent_id
            }
            cited_sources.append(cited_source)
        
        # If no explicit citations found, check for content similarity
        # This helps with follow-up questions where the model might not include citation markers
        if not cited_sources and len(src_map) > 0:
            logger.info("No explicit citations found, checking for content similarity")
            
            # For follow-up questions, include the most relevant sources
            # This is a simple approach - in a production system, you might want to use
            # more sophisticated text similarity measures
            for sid, sinfo in src_map.items():
                # Check if significant content from the source appears in the answer
                source_content = sinfo["content"].lower()
                answer_lower = answer.lower()
                
                # Extract key sentences or phrases from the source
                source_sentences = re.split(r'(?<=[.!?])\s+', source_content)
                significant_content_found = False
                
                # Check if any significant sentences from the source appear in the answer
                for sentence in source_sentences:
                    # Only check sentences that are substantial enough to be meaningful
                    if len(sentence) > 30 and sentence in answer_lower:
                        significant_content_found = True
                        logger.info(f"Source {sid} content found in answer without explicit citation")
                        break
                
                # If significant content found, add this source
                if significant_content_found:
                    parent_id = sinfo.get("parent_id", "")
                    cited_source = {
                        "id": sid,
                        "title": sinfo["title"],
                        "content": sinfo["content"],
                        "parent_id": parent_id
                    }
                    cited_sources.append(cited_source)
        
        logger.info(f"Found {len(cited_sources)} cited sources (explicit and implicit)")
        return cited_sources

    def _get_enhanced_query(self, query: str, query_id: str) -> str:
        """
        Enhance the user query with conversation history.
        Uses chat.completions exclusively for compatibility with GPT-4o, and falls back safely.
        """
        
        # Get the last few messages from the history
        history = self.conversation_manager.get_history()[-5:]
        
        # Create a prompt for the enhancement
        prompt = "Based on the following conversation history, please generate a concise and informative search query that captures the user's intent. The query should be self-contained and not require the conversation history to be understood. Focus on the most recent user query and the key entities and topics discussed.\n\n"
        
        for msg in history:
            prompt += f"{msg['role']}: {msg['content']}\n"
            
        prompt += f"\nGenerate a search query for the last user message: '{query}'"
        
        try:
            messages = [{"role": "user", "content": prompt}]
            enhanced_query_text = self.openai_service.get_chat_response(
                messages=messages,
                temperature=0.2,
                max_completion_tokens=100,
                top_p=1.0,
                presence_penalty=0.0,
                frequency_penalty=0.0,
                query_id=query_id,
                scenario= "query_enhancement"
            )
            enhanced_query = (enhanced_query_text or "").strip()
            logger.info(f"Enhanced query (chat-only): {enhanced_query}")
            return enhanced_query if enhanced_query else query
        except Exception as e:
            logger.error(f"Chat-only enhancement failed: {e}", exc_info=True)
            return query

    def _self_critique_validation(self, answer: str, query: str, context: str, query_id: str, user_id:int,persona: str = None) -> Dict[str, Any]:
        """
        Perform self-critique validation on a generated response.
        
        Args:
            answer: The original response to validate
            query: The user's query
            context: The source context used to generate the response
            query_id: Unique identifier for this query
            persona: The persona to use for policy selection (defaults to current persona)
            
        Returns:
            Dictionary containing:
                - original_response: The unfiltered original answer
                - refined_response: The verified and filtered answer
                - verification_log: List of verification details for each claim
                - verification_summary: Summary statistics
                - policy_selected: The policy used for verification
        """
        import json
        import re
        
        if persona is None:
            persona = self.settings.get('persona', get_persona())
        
        logger.info(f"[SELF-CRITIQUE] Starting validation for persona '{persona}'")
        critique_start_time = time.time()
        
        # Get persona-specific policy
        persona_config = get_persona_config(persona)
        policy_header = persona_config.get('self_critique_policy', 'Balanced Mode: Allow semantic paraphrasing.')
        
        # Format the critique prompt
        critique_prompt = ADVANCED_SELF_CRITIQUE_PROMPT_TEMPLATE.format(
            policy_header=policy_header,
            context=context,
            query=query
        )
        
        try:
            # Call LLM with the critique prompt
            messages = [
                {"role": "system", "content": "You are a meticulous verification assistant. Your task is to validate responses against source material using structured reasoning."},
                {"role": "user", "content": critique_prompt}
            ]
            
            logger.info(f"[SELF-CRITIQUE] Calling LLM for validation (persona: {persona})")
            
            # Use lower temperature for more consistent JSON output
            critique_response = self.openai_service.get_chat_response(
                messages=messages,
                temperature=0.1,  # Low temperature for structured output
                max_completion_tokens=2000,  # Enough for detailed verification
                top_p=1.0,
                presence_penalty=0.0,
                frequency_penalty=0.0,
                query_id=query_id,
                scenario='self_critique_validation',
                user_id=user_id,
                return_usage=True
            )
            
            # Handle tuple response if usage is returned
            prompt_tokens = completion_tokens = total_tokens = None
            if isinstance(critique_response, tuple):
                critique_response, usage = critique_response
                prompt_tokens = usage.get('prompt_tokens')
                completion_tokens = usage.get('completion_tokens')
                total_tokens = usage.get('total_tokens')
            
            logger.info(f"[SELF-CRITIQUE] Received response, parsing JSON...")
            
            # Parse the JSON response
            # Remove markdown code fences if present
            critique_response = critique_response.strip()
            if critique_response.startswith('```'):
                # Remove opening fence
                critique_response = re.sub(r'^```(?:json)?\s*\n', '', critique_response)
                # Remove closing fence
                critique_response = re.sub(r'\n```\s*$', '', critique_response)
            
            try:
                critique_data = json.loads(critique_response)
            except json.JSONDecodeError as je:
                logger.error(f"[SELF-CRITIQUE] JSON parsing failed: {je}")
                logger.error(f"[SELF-CRITIQUE] Raw response: {critique_response[:500]}...")
                # Fallback: return original answer without critique
                return {
                    'original_response': answer,
                    'refined_response': answer,
                    'verification_log': [],
                    'verification_summary': {'error': 'JSON parsing failed'},
                    'policy_selected': policy_header,
                    'critique_failed': True
                }
            
            # Extract the key components
            original_response = critique_data.get('original_response', answer)
            self_critique = critique_data.get('self_critique', {})
            
            refined_response = self_critique.get('final_answer', answer)
            verification_log = self_critique.get('verification_log', [])
            verification_summary = self_critique.get('verification_summary', {})
            policy_selected = self_critique.get('policy_selected', policy_header)
            
            logger.info(f"[SELF-CRITIQUE] Validation complete:")
            logger.info(f"  - Original length: {len(original_response)} chars")
            logger.info(f"  - Refined length: {len(refined_response)} chars")
            logger.info(f"  - Verification items: {len(verification_log)}")
            logger.info(f"  - Policy: {policy_selected}")
            
            # Log summary statistics
            if verification_summary:
                totals = verification_summary.get('totals', {})
                total_sentences = totals.get('sentences', 0)
                violations = verification_summary.get('policy_violations', 0)
                
                # Calculate pass rate
                if total_sentences > 0:
                    pass_rate = (total_sentences - violations) / total_sentences
                else:
                    pass_rate = 1.0 if not violations else 0.0
                    
                pass_percentage = pass_rate * 100
                threshold = 80.0
                status = "PASS" if pass_percentage >= threshold else "FAIL"
                
                logger.info(f"  - Verification totals: {totals}")
                logger.info(f"  - Avg confidence: {verification_summary.get('average_confidence', 'N/A')}")
                logger.info(f"  - Policy violations: {violations}")
                logger.info(f"  - Score: {violations}/{total_sentences} violations ({pass_percentage:.1f}% valid)")
                logger.info(f"  - Status: {status} (Threshold: {threshold}%)")
                
                # Add status to verification summary for downstream use
                verification_summary['status'] = status
                verification_summary['pass_percentage'] = pass_percentage

            
            # Log to DB using metrics collector
            try:
                # Calculate latency
                critique_end_time = time.time()
                critique_latency_ms = int((critique_end_time - critique_start_time) * 1000)
                
                # Extract token usage if available (from a tuple response or potentially enhanced service logic)
                # Note: get_chat_response might return just content or (content, usage) depending on flags
                # In this specific call, we didn't initially ask for usage, but we should if we want it.
                # However, changing the call signature might break things if not careful. 
                # For now, let's assume we can get usage if we update the call or if we use the robust logging pattern.
                
                # To get tokens, we need to ask for return_usage=True in the call above.
                # Let's fix the call first (in a separate step if needed, or assume we update it here).
                # Wait, I can't easily change the call inside this chunk without replacing the whole block.
                # I'll update the logic to validly log what we have and maybe placeholder tokens if missing,
                # BUT the robust solution is to update the get_chat_response call to return usage.
                
                pass_percentage = verification_summary.get('pass_percentage', 0.0)
                status = verification_summary.get('status', 'UNKNOWN')


                self_critique_metrics= SelfCritiqueMetrics(
                    query_id=query_id,
                    refined_response=refined_response,
                    critique_json=critique_data,
                    verification_summary=verification_summary,
                    status=status,
                )
                
                # Helper to update tokens if we had them (future proofing)
                if 'usage' in critique_data: 
                     # unlikely to be in critique_data json but maybe passed separately?
                     pass

                # Log to DB
                connection = get_connection();
                connection.save_self_critique_metrics(self_critique_metrics)
                logger.info(f"[SELF-CRITIQUE] Logged metrics to DB (id={query_id})")
                
            except Exception as log_e:
                logger.error(f"[SELF-CRITIQUE] Logging failed: {log_e}")

            return {
                'original_response': original_response,
                'refined_response': refined_response,
                'verification_log': verification_log,
                'verification_summary': verification_summary,
                'policy_selected': policy_selected,
                'critique_failed': False
            }
            
        except Exception as e:
            logger.error(f"[SELF-CRITIQUE] Validation failed: {e}", exc_info=True)
            # Fallback: return original answer without critique
            return {
                'original_response': answer,
                'refined_response': answer,
                'verification_log': [],
                'verification_summary': {'error': str(e)},
                'policy_selected': policy_header,
                'critique_failed': True
            }

    # ─────────── public API ───────────────
    def generate_rag_response(
            self, query: str, is_enhanced: bool = False, session_id: Optional[str] = None,
            source_url: Optional[str] = None
    ) -> Tuple[str, List[Dict], List[Dict], Dict[str, Any], str]:
        """
        Generate a response using RAG with conversation history.
        
        Args:
            query: The user query
            is_enhanced: A flag to indicate if the query is already enhanced
            
        Returns:
            answer, cited_sources, [], evaluation, context
        """
        # Start total latency timer
        total_start_time = time.time()

        # Save Query
        saved_query = None
        try:
            query_obj = Queries(
                session_id=self.settings.get('user_session').id,
            )
            connection = get_connection();
            saved_query = connection.save_query(query_obj)
            logger.info(f"Query details saved successfully for query_id={saved_query.query_id}")
        except Exception as qd_exc:
            logger.error(f"Failed to save query details: {qd_exc}")

        # Use DB query_id if available, otherwise generate a synthetic one (CLI/RADAR eval mode)
        if saved_query and hasattr(saved_query, 'query_id') and saved_query.query_id is not None:
            query_id = saved_query.query_id
        else:
            import hashlib
            synthetic_id = int(hashlib.md5(f"{session_id or 'cli'}-{time.time()}".encode()).hexdigest()[:8], 16)
            query_id = synthetic_id
            logger.warning(f"Using synthetic query_id={query_id} (DB unavailable)")
        
        # Sync settings with current session state
        # This ensures the assistant uses the correct persona even if cached
        # PRIORITIZE injected persona (if available) over session persona to avoid race conditions
        self.settings['persona'] = self.settings.get('persona') or get_persona()
        logger.info(f"[PERSONA-TRACE] generate_rag_response: settings['persona']={self.settings.get('persona')}, get_persona()={get_persona()}")
        
        try:
            
            # Query enhancement is persona-aware
            enable_enhancement = self.get_persona_setting('enable_query_enhancement', True)
            if enable_enhancement and not is_enhanced:
                logger.info(f"Persona '{self.settings.get('persona')}': Query enhancement enabled")
                logger.info(f"Original query: {query}")
                enhanced_query = self._get_enhanced_query(query, query_id)
                logger.info(f"Enhanced query: {enhanced_query}")
                logger.debug(f"Enhanced query generated: type={type(enhanced_query).__name__}, value='{str(enhanced_query)[:200]}'")
            else:
                if not enable_enhancement:
                    logger.info(f"Persona '{get_persona()}': Query enhancement disabled (using original query)")
                enhanced_query = query
                logger.debug(f"Using provided query without enhancement: type={type(enhanced_query).__name__}, value='{str(enhanced_query)[:200]}'")
            
            # Fallback if enhancement produced empty or non-string
            if not isinstance(enhanced_query, str) or not enhanced_query.strip():
                logger.warning("Enhanced query empty; falling back to original user query")
                enhanced_query = query
            
            # Start search latency timer
            search_start_time = time.time()
            kb_results_raw = self.search_knowledge_base(enhanced_query, query_id)
            search_end_time = time.time()
            search_latency_ms = int((search_end_time - search_start_time) * 1000)

            logger.debug(
                f"KB search returned: type={type(kb_results_raw).__name__}, length={len(kb_results_raw) if hasattr(kb_results_raw, '__len__') else 'n/a'}")
            if kb_results_raw and isinstance(kb_results_raw, list):
                sample = kb_results_raw[0]
                logger.debug(
                    f"KB first item keys: {list(sample.keys()) if isinstance(sample, dict) else 'non-dict item'}")
            if not kb_results_raw:
                return (
                    "No relevant information found in the knowledge base.",
                    [],
                    [],
                    {},
                    "",
                )
            
            # Apply reranking if enabled (non-blocking, falls back to original order)
            rerank_latency_ms = 0  # Default to 0 when reranking is skipped
            enable_reranker = self.get_persona_setting('enable_reranker', True)
            if self.reranker.enabled and enable_reranker:
                logger.info(f"Persona '{get_persona()}': Reranking enabled")
                rerank_start_time = time.time()
                # Get query embedding for cosine reranking
                query_embedding = self.generate_embedding(enhanced_query, query_id,'reranking_query_embedding')
                kb_results_raw = self.reranker.rerank(
                    query=enhanced_query,
                    query_embedding=query_embedding,
                    documents=kb_results_raw,
                    top_k=10,
                    query_id=query_id
                )
                rerank_end_time = time.time()
                rerank_latency_ms = int((rerank_end_time - rerank_start_time) * 1000)
                logger.info(f"Reranking completed in {rerank_latency_ms}ms")
            else:
                if not enable_reranker:
                    logger.info(f"Persona '{get_persona()}': Reranking disabled (using original search order)")

            
            try:
                kb_results = dedupe_sources_by_key(kb_results_raw, content_field="chunk")
            except Exception as dedupe_exc:
                # Log detailed context to diagnose schema mismatches
                logger.error(f"Error deduplicating KB results: {dedupe_exc}", exc_info=True)
                logger.error(
                    f"kb_results_raw sample (first 1-2 items): {kb_results_raw[:2] if isinstance(kb_results_raw, list) else kb_results_raw}")
                return (
                    "I encountered an error while preparing knowledge base results.",
                    [],
                    [],
                    {},
                    "",
                )

            context, src_map = self._prepare_context(kb_results)
            
            # Use the conversation history to generate the answer
            # Start LLM latency timer
            llm_start_time = time.time()
            # Use the conversation history to generate the answer
            # Start LLM latency timer
            llm_start_time = time.time()
            answer_result = self._chat_answer_with_history(query, context, src_map, query_id)

            # Handle tuple return (answer, usage)
            if isinstance(answer_result, tuple):
                answer, usage_info = answer_result
                prompt_tokens = usage_info.get('prompt_tokens')
                completion_tokens = usage_info.get('completion_tokens')
                total_tokens = usage_info.get('total_tokens')
            else:
                answer = answer_result
                prompt_tokens = completion_tokens = total_tokens = None
                
            # End LLM latency timer
            llm_end_time = time.time()
            llm_latency_ms = int((llm_end_time - llm_start_time) * 1000)

            # Apply correction loop if enabled (Scientist persona only)
            # RADAR multi-dimensional correction is preferred over legacy binary groundedness
            correction_result = None
            enable_radar_correction = self.get_persona_setting('enable_radar_correction', False)
            enable_correction_loop = self.get_persona_setting('enable_correction_loop', False)
            if enable_radar_correction:
                # RADAR: Multi-dimensional correction with engagement preservation
                self_correct_mode = self.get_persona_setting('self_correct_mode', 'true')

                # Skip RADAR entirely if self_correct_mode is 'false'
                if self_correct_mode == 'false':
                    logger.info(f"Persona '{get_persona()}': RADAR skipped (self_correct_mode=false)")
                else:
                    try:
                        from services.radar_correction_loop import RadarCorrectionLoop

                        radar_thresholds = self.get_persona_setting('radar_correction_thresholds', {})
                        radar_temperature = self.get_persona_setting('radar_correction_temperature', 0.6)
                        radar_max_rounds = self.get_persona_setting('radar_correction_max_rounds', 1)

                        logger.info(
                            f"Persona '{get_persona()}': RADAR enabled (self_correct_mode={self_correct_mode}, temp={radar_temperature})")

                        radar_loop = RadarCorrectionLoop(
                            thresholds=radar_thresholds if radar_thresholds else None,
                            temperature=radar_temperature,
                            max_rounds=radar_max_rounds,
                            use_responses_api=self.get_persona_setting('use_responses_api', False),
                            verbosity=self.get_persona_setting('verbosity', None),
                            reasoning_effort=self.get_persona_setting('reasoning_effort', None),
                            responses_api_version=self.get_persona_setting('responses_api_version', '2025-03-01-preview'),
                        )

                        if self_correct_mode == 'evaluate_only':
                            # Just evaluate, don't correct
                            radar_result = radar_loop.evaluate_only(
                                draft=answer,
                                query_id=query_id,
                                query=query,
                                context=context
                            )
                            correction_result = type('CorrectionResult', (), {
                                'was_corrected': False,
                                'rounds_used': 0,
                                'evaluation': {
                                    'radar_scores': radar_result.radar_scores,
                                    'radar_reasons': radar_result.radar_reasons,
                                    'failing_dimensions': radar_result.failing_dimensions,
                                    'original_draft': answer,
                                    'corrected_response': None
                                }
                            })()
                        else:
                            # Default: Run correction (self_correct_mode == 'true')
                            radar_result = radar_loop.correct_response(
                                draft=answer,
                                query_id=query_id,
                                query=query,
                                context=context
                            )

                            if radar_result.was_corrected:
                                logger.info(
                                    f"RADAR correction applied: failing dimensions={radar_result.failing_dimensions}, rounds_used={radar_result.rounds_used}")
                                original_draft = answer  # Store original before replacing
                                answer = radar_result.final_response
                                correction_result = type('CorrectionResult', (), {
                                    'was_corrected': True,
                                    'rounds_used': radar_result.rounds_used,
                                    'evaluation': {
                                        'radar_scores': radar_result.radar_scores,
                                        'radar_reasons': radar_result.radar_reasons,
                                        'failing_dimensions': radar_result.failing_dimensions,
                                        'original_draft': original_draft,
                                        'corrected_response': radar_result.final_response
                                    }
                                })()
                            else:
                                logger.info(f"RADAR: No correction needed, scores={radar_result.radar_scores}")
                                correction_result = type('CorrectionResult', (), {
                                    'was_corrected': False,
                                    'rounds_used': 0,
                                    'evaluation': {
                                        'radar_scores': radar_result.radar_scores,
                                        'radar_reasons': radar_result.radar_reasons,
                                        'failing_dimensions': [],
                                        'original_draft': answer,
                                        'corrected_response': None
                                    }
                                })()

                    except ImportError as e:
                        logger.warning(f"RADAR correction loop not available: {e}")
                    except Exception as e:
                        logger.error(f"RADAR correction loop failed: {e}", exc_info=True)
                        # Continue with original answer on failure

            elif enable_correction_loop:
                # Legacy: Binary groundedness correction (deprecated in favor of RADAR)
                try:
                    from services.correction_loop import CorrectionLoop
                    correction_threshold = self.get_persona_setting('correction_threshold', 0.75)
                    max_correction_rounds = self.get_persona_setting('max_correction_rounds', 1)
                    
                    logger.info(f"Persona '{get_persona()}': Legacy correction loop enabled (threshold={correction_threshold})")

                    correction_loop = CorrectionLoop()
                    correction_result = correction_loop.correct_response(
                        draft=answer,
                        query=query,
                        context=context,
                        max_rounds=max_correction_rounds,
                        threshold=correction_threshold,
                        persona=get_persona(),
                        query_id=query_id
                    )
                    
                    if correction_result.was_corrected:
                        logger.info(f"Legacy correction applied: score improved from draft to final, rounds_used={correction_result.rounds_used}")
                        answer = correction_result.final_response
                    else:
                        logger.info(f"No correction needed: score={correction_result.evaluation.get('score', 'n/a')}")
                        
                except ImportError as e:
                    logger.warning(f"Correction loop not available: {e}")
                except Exception as e:
                    logger.error(f"Correction loop failed: {e}", exc_info=True)
                    # Continue with original answer on failure


            # Apply self-critique validation if enabled
            critique_result = None
            enable_self_critique = self.get_persona_setting('enable_self_critique', False)
            async_self_critique = self.get_persona_setting('async_self_critique', False)
            
            if enable_self_critique:
                current_persona = get_persona()
                
                if async_self_critique:
                    # Run self-critique in background thread (doesn't block response)
                    # This is used for Intermediate mode where critique is for logging only
                    def run_async_critique(user_id):
                        try:
                            logger.info(f"Persona '{current_persona}': Running ASYNC self-critique (non-blocking)")
                            result = self._self_critique_validation(
                                answer=answer,
                                query=query,
                                context=context,
                                query_id=query_id,
                                persona=current_persona,
                                user_id=user_id
                            )
                            if not result.get('critique_failed', False):
                                logger.info(f"ASYNC self-critique completed: verification_summary={result.get('verification_summary', {})}")
                            else:
                                logger.warning("ASYNC self-critique failed")
                        except Exception as e:
                            logger.error(f"ASYNC self-critique error: {e}", exc_info=True)

                    user_id = _get_user_id()
                    thread = threading.Thread(target=run_async_critique,args=(user_id,), daemon=True)
                    thread.start()
                    logger.info(f"Self-critique running in background thread for persona '{current_persona}'")
                else:
                    # Synchronous self-critique (can modify the answer)
                    try:
                        logger.info(f"Persona '{current_persona}': Self-critique enabled (sync)")
                        
                        critique_result = self._self_critique_validation(
                            answer=answer,
                            query=query,
                            context=context,
                            query_id=query_id,
                            persona=current_persona,
                            user_id=_get_user_id()
                        )
                        
                        if not critique_result.get('critique_failed', False):
                            # Use the refined response
                            original_answer = answer
                            answer = critique_result['refined_response']
                            logger.info(f"Self-critique applied: original={len(original_answer)} chars, refined={len(answer)} chars")
                            logger.info(f"Verification summary: {critique_result.get('verification_summary', {})}")
                        else:
                            logger.warning("Self-critique failed, using original answer")
                            
                    except Exception as e:
                        logger.error(f"Self-critique validation failed: {e}", exc_info=True)
                        # Continue with original answer on failure

            # Collect only the sources actually cited
            cited_raw = self._filter_cited(answer, src_map)

            # Deduplicate cited sources by document (prefer parent_id, fallback to normalized title)
            # First pass: record first occurrence per document and map old chunk ids to doc_key
            doc_entries = []
            doc_keys = []
            oldid_to_dockey = {}
            for src in cited_raw:
                doc_key = src.get("parent_id") or src.get("title", "").strip().lower()
                if doc_key not in doc_keys:
                    doc_keys.append(doc_key)
                    doc_entries.append(src)
                oldid_to_dockey[src["id"]] = doc_key

            # Second pass: assign new ids per document and build final cited_sources
            dockey_to_newid = {}
            cited_sources = []
            for new_id, src in enumerate(doc_entries, 1):
                doc_key = src.get("parent_id") or src.get("title", "").strip().lower()
                dockey_to_newid[doc_key] = str(new_id)
                entry = {
                    "id": str(new_id),
                    "title": src["title"],
                    "content": src["content"],
                    "parent_id": src.get("parent_id", "")
                }
                if "url" in src:
                    entry["url"] = src["url"]
                cited_sources.append(entry)

            # Renumber all old chunk-level citations in the answer to the document-level ids
            def renumber_callback(match):
                old_id = match.group(1)
                doc_key = oldid_to_dockey.get(old_id)
                if doc_key:
                    new_id_val = dockey_to_newid.get(doc_key)
                    if new_id_val:
                        return f"[{new_id_val}]"
                return match.group(0)

            answer = re.sub(r"\[(\d+)\]", renumber_callback, answer)
            # Collapse immediately repeated citations like [1][1] -> [1]
            answer = compress_adjacent_duplicate_citations(answer)

            # Get evaluation

            try:

                if self.get_persona_setting('enable_groundedness_check', False):

                    eval_result = self.fact_checker.evaluate_response(
                        query=query,
                        answer=answer,
                        context=context,
                        persona=self.settings.get('persona', get_persona()),
                        query_id=query_id
                    )

                    evaluation = eval_result.to_dict() if hasattr(eval_result, 'to_dict') else eval_result

                else:

                    evaluation = {}

            except Exception as e:

                logger.warning(f"Evaluation failed: {e}")

                evaluation = {}

            

            # Calculate total latency
            total_end_time = time.time()
            total_latency_ms = int((total_end_time - total_start_time) * 1000)
            
            # Log the query, response, and sources to the database
            try:
                # Calculate turn index from conversation history (count user messages)
                try:
                    history = self.conversation_manager.get_history()
                    turn_index = sum(1 for msg in history if msg.get('role') == 'user')
                except Exception:
                    turn_index = None


                current_mode = get_mode()
                current_features = get_persona_config(self.settings.get('persona', get_persona()))

                # Merge RADAR evaluation results into features_json for logging
                if correction_result is not None:
                    radar_eval = getattr(correction_result, 'evaluation', None)
                    if radar_eval:
                        # Data from the dynamically created correction_result object
                        current_features['radar_evaluation'] = {
                            'scores': radar_eval.get('radar_scores', {}),
                            'reasons': radar_eval.get('radar_reasons', {}),
                            'failing_dimensions': radar_eval.get('failing_dimensions', []),
                            'was_corrected': getattr(correction_result, 'was_corrected', False),
                            'rounds_used': getattr(correction_result, 'rounds_used', 0),
                            'original_draft': radar_eval.get('original_draft'),
                            'corrected_response': radar_eval.get('corrected_response'),
                            'eval_prompt_tokens': radar_eval.get('eval_prompt_tokens', 0),
                            'eval_completion_tokens': radar_eval.get('eval_completion_tokens', 0),
                            'correction_prompt_tokens': radar_eval.get('correction_prompt_tokens', 0),
                            'correction_completion_tokens': radar_eval.get('correction_completion_tokens', 0),
                            'total_radar_tokens': radar_eval.get('total_radar_tokens', 0)
                        }
                    elif hasattr(correction_result, 'radar_scores'):
                        # Direct RadarCorrectionResult object (from legacy path)
                        current_features['radar_evaluation'] = {
                            'scores': correction_result.radar_scores,
                            'reasons': getattr(correction_result, 'radar_reasons', {}),
                            'failing_dimensions': correction_result.failing_dimensions,
                            'was_corrected': correction_result.was_corrected,
                            'rounds_used': correction_result.rounds_used,
                            'original_draft': correction_result.original_draft,
                            'corrected_response': correction_result.final_response if correction_result.was_corrected else None,
                            'eval_prompt_tokens': getattr(correction_result, 'eval_prompt_tokens', 0),
                            'eval_completion_tokens': getattr(correction_result, 'eval_completion_tokens', 0),
                            'correction_prompt_tokens': getattr(correction_result, 'correction_prompt_tokens', 0),
                            'correction_completion_tokens': getattr(correction_result, 'correction_completion_tokens',
                                                                    0),
                            'total_radar_tokens': getattr(correction_result, 'total_radar_tokens', 0)
                        }
                # Save QueryDetails response update
                try:
                    connection = get_connection();
                    query_details = QueryDetails(
                        query_id=query_id,
                        user_query=query,
                        response=answer,
                        latency_ms=total_latency_ms,
                        is_follow_up=turn_index > 1 if turn_index is not None else False,
                        mode=current_mode,
                        persona=self.settings.get('persona', get_persona()),
                        llm_latency_ms=llm_latency_ms,
                        search_latency_ms=search_latency_ms,
                        reranker_latency_ms=rerank_latency_ms,
                        sources=cited_sources,
                        features_json=current_features
                    )
                    connection.save_query_details(query_details)
                    logger.info(f"QueryDetails updated successfully for query_id={query_id}")
                except Exception as exc:
                    logger.error(f"Failed to update QueryDetails for query_id={query_id}: {exc}")
                
                logger.info(f"Latency metrics (robust): search={search_latency_ms}ms, rerank={rerank_latency_ms}ms, llm={llm_latency_ms}ms, total={total_latency_ms}ms")
            except Exception as log_exc:
                logger.error(f"Error logging RAG interaction (robust): {log_exc}")
                # Interaction continues even if logging fails (but collector already blasted CRITICAL)
            
            # Add self-critique metadata to evaluation if available
            if critique_result and not critique_result.get('critique_failed', False):
                evaluation['self_critique'] = {
                    'verification_summary': critique_result.get('verification_summary', {}),
                    'policy_selected': critique_result.get('policy_selected', ''),
                    'verification_log': critique_result.get('verification_log', [])
                }
            
            return answer, cited_sources, [], evaluation, context
        
        except Exception as exc:
            logger.error(f"RAG generation error: {exc}", exc_info=True)
            return (
                "I encountered an error while generating the response.",
                [],
                [],
                {},
                "",
            )

    def stream_rag_response(self, query: str, is_enhanced: bool = False, session_id: Optional[str] = None,
                            source_url: Optional[str] = None) -> Generator[Union[str, Dict], None, None]:
        """
        Stream the RAG response generation with conversation history.
        
        Args:
            query: The user query
            is_enhanced: A flag to indicate if the query is already enhanced
            
        Yields:
            Either string chunks of the answer or a dictionary with metadata
        """
        # Start total latency timer
        usage_obj = None
        total_start_time = time.time()
        # Save Query
        saved_query = None
        try:
            # Safeguard: ensure user_session exists
            user_session = self.settings.get('user_session')
            if user_session is None:
                logger.warning("user_session is None, cannot save query to database")
                # Generate a temporary query_id for this session
                import uuid
                query_id = str(uuid.uuid4())
                logger.info(f"Using temporary query_id: {query_id}")
            else:
                query_obj = Queries(
                    session_id=user_session.id,
                )
                connection = get_connection();
                saved_query = connection.save_query(query_obj)
                logger.info(f"Query details saved successfully for query_id={saved_query.query_id}")
                query_id = saved_query.query_id
        except Exception as qd_exc:
            logger.error(f"Failed to save query details: {qd_exc}")
            # Generate fallback ID instead of crashing
            import uuid
            query_id = str(uuid.uuid4())
            logger.warning(f"Using fallback query_id: {query_id}")
        
        # CRITICAL: Capture persona NOW while Flask request context is still available
        # Once we start yielding, the request context is lost and get_persona() returns 'explorer' default
        # Sync settings with current session state to ensure consistency throughout the stream
        # PRIORITIZE injected persona (if available) over session persona
        self.settings['persona'] = self.settings.get('persona') or get_persona()
        current_persona = self.settings['persona']
        current_mode = get_mode()  # Capture mode while Flask context is available
        current_features = get_persona_config(current_persona)  # Snapshot features for logging
        logger.info(f"[PERSONA] Captured persona at stream start: {current_persona}, mode: {current_mode}")
        
        try:
            logger.info(f"========== STARTING STREAM RAG RESPONSE WITH HISTORY ==========")
            logger.info(f"Original query: {query}")
            logger.info(f"Session ID: {session_id}, Source URL: {source_url}, Persona: {current_persona}")
            
            # Query enhancement is persona-aware (same as generate_rag_response)
            logger.debug(f"stream_rag_response: is_enhanced={is_enhanced}")
            enable_enhancement = self.get_persona_setting('enable_query_enhancement', True)
            if enable_enhancement and not is_enhanced:
                logger.info(f"Persona '{current_persona}': Query enhancement enabled (streaming)")
                logger.info(f"Original query: {query}")
                enhanced_query = self._get_enhanced_query(query, query_id)
                logger.info(f"Original query: {query} | Enhanced query: {enhanced_query}")
                logger.debug(f"Enhanced query generated: type={type(enhanced_query).__name__}, value='{str(enhanced_query)[:200]}'")
            else:
                if not enable_enhancement:
                    logger.info(f"Persona '{current_persona}': Query enhancement disabled (streaming, using original query)")
                enhanced_query = query
                logger.debug(
                    f"Using provided query without enhancement: type={type(enhanced_query).__name__}, value='{str(enhanced_query)[:200]}'")
            # Fallback if enhancement produced empty or non-string
            if not isinstance(enhanced_query, str) or not enhanced_query.strip():
                logger.warning("Enhanced query empty; falling back to original user query")
                enhanced_query = query
            
            # Start search latency timer
            search_start_time = time.time()
            kb_results_raw = self.search_knowledge_base(enhanced_query, query_id)
            search_end_time = time.time()
            search_latency_ms = int((search_end_time - search_start_time) * 1000)
            
            # Initialize rerank latency (will be set if reranking is enabled)
            rerank_latency_ms = 0  # Default to 0 when reranking is skipped
            
            if not kb_results_raw:
                logger.info("No relevant information found in knowledge base")
                yield "No relevant information found in the knowledge base."
                yield {
                    "sources": [],
                    "evaluation": {}
                }
                return
            
            # Apply reranking if enabled (persona-aware, same as generate_rag_response)
            enable_reranker = self.get_persona_setting('enable_reranker', True)
            if self.reranker.enabled and enable_reranker:
                logger.info(f"Persona '{current_persona}': Reranking enabled (streaming)")
                rerank_start_time = time.time()
                # Get query embedding for cosine reranking
                query_embedding = self.generate_embedding(enhanced_query, query_id, 'reranking_query_embedding_stream')
                kb_results_raw = self.reranker.rerank(
                    query=enhanced_query,
                    query_embedding=query_embedding,
                    documents=kb_results_raw,
                    top_k=10,
                    query_id = query_id
                )
                rerank_end_time = time.time()
                rerank_latency_ms = int((rerank_end_time - rerank_start_time) * 1000)
                logger.info(f"Reranking completed in {rerank_latency_ms}ms")
            else:
                if not enable_reranker:
                    logger.info(f"Persona '{current_persona}': Reranking disabled (streaming, using original search order)")
            
            try:
                kb_results = dedupe_sources_by_key(kb_results_raw, content_field="chunk")
            except Exception as dedupe_exc:
                # Log detailed context to diagnose schema mismatches
                logger.error(f"Error deduplicating KB results: {dedupe_exc}", exc_info=True)
                logger.error(
                    f"kb_results_raw sample (first 1-2 items): {kb_results_raw[:2] if isinstance(kb_results_raw, list) else kb_results_raw}")
                yield "I encountered an error while preparing knowledge base results."
                yield {
                    "sources": [],
                    "evaluation": {},
                    "error": str(dedupe_exc)
                }
                return
            
            context, src_map = self._prepare_context(kb_results)
            logger.info(f"Retrieved {len(kb_results)} results from knowledge base (search={search_latency_ms}ms)")
            
            # Check if custom prompt is available in settings
            settings = self.settings
            custom_prompt = settings.get("custom_prompt", "")
            
            # Apply custom prompt to query if available
            if custom_prompt:
                query = f"{custom_prompt}\n\n{query}"
                logger.info(f"Applied custom prompt to query: {custom_prompt[:100]}...")
            
            # Create a context message
            context_message = f"<context>\n{context}\n</context>\n<user_query>\n{query}\n</user_query>"
            
            # Add the user message to conversation history
            self.conversation_manager.add_user_message(context_message)
            
            # Get the complete conversation history
            raw_messages = self.conversation_manager.get_history()
            
            # Trim history if needed
            messages, trimmed = self._trim_history(raw_messages, query_id)
            if trimmed:
                # Log trimming notification (don't yield metadata here - it breaks streaming protocol)
                # Frontend expects all text before [[META]] separator, so metadata must only be yielded at the end
                logger.info(f"Conversation history trimmed: dropped {len(raw_messages) - len(messages)} messages")
            
            # Log the conversation history
            logger.info(f"Conversation history has {len(messages)} messages (trimmed: {trimmed})")
            for i, msg in enumerate(messages):
                logger.info(f"Message {i} - Role: {msg['role']}")
                if i < 3 or i >= len(messages) - 2:  # Log first 3 and last 2 messages
                    logger.info(f"Content: {msg['content'][:100]}...")
            
            # Stream the response
            collected_chunks = []
            collected_answer = ""
            

            # Check if persona uses Responses API (e.g., Scientist with high reasoning/verbosity)
            use_responses_api = self.get_persona_setting('use_responses_api', False)
            responses_api_version = self.get_persona_setting('responses_api_version', '2025-03-01-preview')
            # Session overrides take priority over persona defaults
            reasoning_effort = get_reasoning_effort() or self.get_persona_setting('reasoning_effort', 'high')
            verbosity = get_verbosity() or self.get_persona_setting('verbosity', 'high')
            
            if use_responses_api:
                # Use the Responses API for streaming (Scientist persona)
                logger.info(f"[RESPONSES API STREAM] Persona '{current_persona}' using Responses API with reasoning={reasoning_effort}, verbosity={verbosity}")
                
                # Start LLM latency timer
                llm_start_time = time.time()
                
                try:
                    # Stream using Responses API
                    for chunk in self.openai_service.stream_responses_api(
                        messages=messages,
                        reasoning_effort=reasoning_effort,
                        verbosity=verbosity,
                        model=self.deployment_name,
                        api_version=responses_api_version,
                    ):
                        # Check if this is usage info dict (yielded at end of stream)
                        if isinstance(chunk, dict) and chunk.get('__usage__'):
                            # Capture usage for metrics logging
                            usage_obj = chunk
                            logger.info(f"[RESPONSES API STREAM] Captured usage: {chunk}")
                        else:
                            collected_chunks.append(chunk)
                            collected_answer += chunk
                            yield chunk
                except Exception as e:
                    logger.error(f"[RESPONSES API STREAM] Error: {e}", exc_info=True)
                    # Fallback to chat.completions if Responses API fails
                    logger.warning("Falling back to chat.completions API")
                    use_responses_api = False  # Trigger fallback below
            
            if not use_responses_api:
                # GPT-5 model family detection - exclude unsupported parameters proactively
                is_gpt5_model = self.deployment_name.lower().startswith('gpt-5')
                if is_gpt5_model:
                    logger.info(f"Detected GPT-5 family model: {self.deployment_name}. Using max_completion_tokens and excluding temperature/top_p/penalties.")
                
                # Use the OpenAI client directly for streaming since our OpenAIService doesn't support streaming yet
                request = {
                    # Arguments for self.openai_client.chat.completions.create
                    'model': self.deployment_name,
                    'messages': messages,
                    'stream': True,
                    'stream_options' : {"include_usage": True},
                }
                
                # Add token limit - GPT-5 uses max_completion_tokens, others use max_tokens
                if is_gpt5_model:
                    request['max_completion_tokens'] = self.max_tokens
                else:
                    request['max_tokens'] = self.max_tokens
                    request['temperature'] = self.temperature
                    request['top_p'] = self.top_p
                    request['presence_penalty'] = self.presence_penalty
                    request['frequency_penalty'] = self.frequency_penalty
                log_openai_call(request, {"type": "stream_started"})
                # Start LLM latency timer
                llm_start_time = time.time()
                try:
                    stream = self.openai_service.client.chat.completions.create(**request)
                except Exception as initial_err:
                    msg = str(initial_err)
                    logger.warning(f"Initial stream chat.completions.create failed: {initial_err}")
                    if ("Unsupported parameter" in msg or "unsupported_parameter" in msg) and ("max_tokens" in msg):
                        if 'max_tokens' in request:
                            mt = request.pop('max_tokens')
                            request['max_completion_tokens'] = mt
                            logger.info(
                                "Retrying stream with 'max_completion_tokens' due to model not supporting 'max_tokens'")
                            try:
                                stream = self.openai_service.client.chat.completions.create(**request)
                            except Exception as second_err:
                                msg2 = str(second_err)
                                if ("Unsupported value" in msg2 or "unsupported_value" in msg2):
                                    removed_any = False
                                    for p in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
                                        if p in request and p in msg2:
                                            removed_any = True
                                            val = request.pop(p)
                                            logger.info(f"Retrying stream after removing unsupported '{p}'={val}")
                                    if removed_any:
                                        stream = self.openai_service.client.chat.completions.create(**request)
                                    else:
                                        raise
                                else:
                                    raise
                        else:
                            raise
                    elif ("Unsupported value" in msg or "unsupported_value" in msg):
                        removed_any = False
                        for p in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
                            if p in request and p in msg:
                                removed_any = True
                                val = request.pop(p)
                                logger.info(f"Retrying stream after removing unsupported '{p}'={val}")
                        if removed_any:
                            stream = self.openai_service.client.chat.completions.create(**request)
                        else:
                            raise
                    else:
                        raise
                # Process the streaming response
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        collected_chunks.append(content)
                        collected_answer += content
                        # Yield the raw content - the client-side will handle markdown rendering
                        # This ensures consistent rendering across all response types
                        yield content
                    # Capture usage info if available (for robust logging later) by setting stream_options include_usage,
                    # which ensures usage is in the final chunk
                    elif hasattr(chunk, "usage") and chunk.usage:
                        usage_obj = chunk.usage



            
            # End LLM latency timer after streaming completes
            llm_end_time = time.time()
            llm_latency_ms = int((llm_end_time - llm_start_time) * 1000)
            
            logger.info("DEBUG - Collected answer: %s", collected_answer[:100])
            
            # Add the assistant's response to conversation history
            self.conversation_manager.add_assistant_message(collected_answer)
            
            # Apply self-critique validation if enabled
            # Note: In streaming mode, we've already yielded the content, so we can't modify it
            # However, we can still run validation for logging and metadata purposes
            critique_result = None
            enable_self_critique = self.get_persona_setting('enable_self_critique', False)
            async_self_critique = self.get_persona_setting('async_self_critique', False)
            
            if enable_self_critique:
                if async_self_critique:
                    # Run self-critique in background thread (doesn't block streaming completion)
                    def run_async_critique_streaming(user_id):
                        try:
                            logger.info(f"Persona '{current_persona}': Running ASYNC self-critique (streaming, non-blocking)")
                            result = self._self_critique_validation(
                                answer=collected_answer,
                                query=query,
                                context=context,
                                query_id=query_id,
                                persona=current_persona,
                                user_id = user_id
                            )
                            if not result.get('critique_failed', False):
                                logger.info(f"ASYNC self-critique completed (streaming): verification_summary={result.get('verification_summary', {})}")
                            else:
                                logger.warning("ASYNC self-critique failed (streaming)")
                        except Exception as e:
                            logger.error(f"ASYNC self-critique error (streaming): {e}", exc_info=True)
                    user_id = _get_user_id()
                    thread = threading.Thread(target=run_async_critique_streaming,args=(user_id,), daemon=True)
                    thread.start()
                    logger.info(f"Self-critique running in background thread (streaming) for persona '{current_persona}'")
                else:
                    # Synchronous self-critique (for logging only in streaming - can't modify already-yielded content)
                    try:
                        logger.info(f"Persona '{current_persona}': Self-critique enabled (streaming)")
                        
                        critique_result = self._self_critique_validation(
                            answer=collected_answer,
                            query=query,
                            context=context,
                            query_id=query_id,
                            persona=current_persona,
                            user_id = _get_user_id()
                        )
                        
                        if not critique_result.get('critique_failed', False):
                            logger.info(f"Self-critique completed (streaming): original={len(collected_answer)} chars, refined={len(critique_result['refined_response'])} chars")
                            logger.info(f"Verification summary: {critique_result.get('verification_summary', {})}")
                            # Note: We don't replace collected_answer here since content was already streamed
                            # The critique result will be included in metadata for transparency
                        else:
                            logger.warning("Self-critique failed in streaming mode")
                            
                    except Exception as e:
                        logger.error(f"Self-critique validation failed (streaming): {e}", exc_info=True)
                        # Continue with original answer on failure
            # Get evaluation
            try:
                # Check if we should run evaluation (Scientist persona or enabled config)
                if self.get_persona_setting('enable_groundedness_check', False):
                    eval_result = self.fact_checker.evaluate_response(
                        query=query,
                        answer=collected_answer,
                        context=context,
                        persona=current_persona,  # Use captured persona from stream start
                        query_id=query_id
                    )
                    # Handle both EvaluationResult object and legacy dict
                    evaluation = eval_result.to_dict() if hasattr(eval_result, 'to_dict') else eval_result
                else:
                    evaluation = {}
            except Exception as e:
                logger.warning(f"Evaluation failed in stream: {e}")
                evaluation = {"error": str(e)}
            
            # Calculate total latency
            total_end_time = time.time()
            total_latency_ms = int((total_end_time - total_start_time) * 1000)
            # Run RADAR for streaming - self_correct_mode: 'true' | 'evaluate_only' | 'false'
            radar_result = None
            original_response = collected_answer
            enable_radar = self.get_persona_setting('enable_radar_correction', False)
            self_correct_mode = self.get_persona_setting('self_correct_mode', 'true')

            if enable_radar and collected_answer and self_correct_mode != 'false':
                try:
                    eval_context = context if 'context' in locals() else ""
                    radar_loop = RadarCorrectionLoop.from_env(
                        use_responses_api=self.get_persona_setting('use_responses_api', False),
                        verbosity=self.get_persona_setting('verbosity', None),
                        reasoning_effort=self.get_persona_setting('reasoning_effort', None),
                        responses_api_version=self.get_persona_setting('responses_api_version', '2025-03-01-preview'),
                    )

                    logger.info(f"RADAR streaming: self_correct_mode={self_correct_mode}")

                    if self_correct_mode == 'evaluate_only':
                        # Just log scores, don't attempt correction
                        radar_result = radar_loop.evaluate_only(
                            draft=collected_answer,
                            query_id=query_id,
                            query=query,
                            context=eval_context
                        )
                    else:
                        # Default (true): Run full correction and replace if needed
                        radar_result = radar_loop.correct_response(
                            draft=collected_answer,
                            query_id=query_id,
                            query=query,
                            context=eval_context
                        )

                        if radar_result.was_corrected:
                            logger.info(
                                f"RADAR correction applied for streaming, replacing response. failing_dims={radar_result.failing_dimensions}")
                            # Update collected_answer for logging AND for citation renumbering
                            collected_answer = radar_result.final_response

                except ImportError as e:
                    logger.warning(f"RADAR correction not available for streaming: {e}")
                except Exception as e:
                    logger.error(f"RADAR correction failed for streaming: {e}", exc_info=True)
            
            # Filter cited sources from the final collected_answer (post-RADAR)
            cited_raw = self._filter_cited(collected_answer, src_map)
            
            # Deduplicate cited sources by document (prefer parent_id, fallback to normalized title)
            # First pass: record first occurrence per document and map old chunk ids to doc_key
            doc_entries = []
            doc_keys = []
            oldid_to_dockey = {}
            for src in cited_raw:
                doc_key = src.get("parent_id") or src.get("title", "").strip().lower()
                if doc_key not in doc_keys:
                    doc_keys.append(doc_key)
                    doc_entries.append(src)
                oldid_to_dockey[src["id"]] = doc_key
            
            # Second pass: assign new ids per document and build final cited_sources
            dockey_to_newid = {}
            cited_sources = []
            for new_id, src in enumerate(doc_entries, 1):
                doc_key = src.get("parent_id") or src.get("title", "").strip().lower()
                dockey_to_newid[doc_key] = str(new_id)
                entry = {
                    "id": str(new_id),
                    "title": src["title"],
                    "content": src["content"],
                    "parent_id": src.get("parent_id", "")
                }
                if "url" in src:
                    entry["url"] = src["url"]
                cited_sources.append(entry)
            
            # Apply renumbering to the answer for all old chunk-level ids
            # Renumber all old chunk-level citations in the answer to the document-level ids
            def renumber_callback(match):
                old_id = match.group(1)
                doc_key = oldid_to_dockey.get(old_id)
                if doc_key:
                    new_id_val = dockey_to_newid.get(doc_key)
                    if new_id_val:
                        return f"[{new_id_val}]"
                return match.group(0)

            collected_answer = re.sub(r"\[(\d+)\]", renumber_callback, collected_answer)
            # Collapse immediately repeated citations like [1][1] -> [1]
            collected_answer = compress_adjacent_duplicate_citations(collected_answer)

            # If RADAR was corrected, we need to send the post-renumbered collected_answer
            if radar_result and radar_result.was_corrected:
                yield {
                    "replace_response": collected_answer,
                    "radar_corrected": True,
                    "failing_dimensions": radar_result.failing_dimensions
                }

            # Success path: Yield the final metadata
            metadata = {
                "sources": cited_sources,
                "evaluation": evaluation,
                "context": context if 'context' in locals() else "",
                "query_id": query_id,
                "renumber_citations": {old: dockey_to_newid[doc_key] for old, doc_key in oldid_to_dockey.items() if doc_key in dockey_to_newid}
            }
            
            # Add self-critique metadata if available
            if critique_result and not critique_result.get('critique_failed', False):
                metadata["self_critique"] = {
                    "verification_summary": critique_result.get('verification_summary', {}),
                    "policy_selected": critique_result.get('policy_selected', ''),
                    "verification_log": critique_result.get('verification_log', [])
                }
            
            logger.info(f"YIELDING METADATA: {metadata}")
            yield metadata
            
        except Exception as exc:
            logger.error("RAG streaming error: %s", exc)
            yield "I encountered an error while generating the response."
            yield {
                "sources": [],
                "evaluation": {},
                "error": str(exc)
            }
        finally:
            # GUARANTEED ROBUST LOGGING
            try:
                # Calculate total latency
                total_end_time = time.time()
                total_latency_ms = int((total_end_time - total_start_time) * 1000)

                # Attempt token extraction (fragile but captured in context)
                try:
                    # usage_obj = getattr(stream, "usage", None) if 'stream' in locals() else None
                    if usage_obj is None and 'stream' in locals() and hasattr(stream, "response"):
                        usage_obj = getattr(stream.response, "usage", None)
                    pt = getattr(usage_obj, "prompt_tokens", None) if usage_obj is not None and not isinstance(usage_obj, dict) else (usage_obj.get("prompt_tokens") if usage_obj else None)
                    ct = getattr(usage_obj, "completion_tokens", None) if usage_obj is not None and not isinstance(usage_obj, dict) else (usage_obj.get("completion_tokens") if usage_obj else None)
                    tt = getattr(usage_obj, "total_tokens", None) if usage_obj is not None and not isinstance(usage_obj, dict) else (usage_obj.get("total_tokens") if usage_obj else None)
                except Exception:
                    pt = ct = tt = None

                # Calculate turn index
                try:
                    history = self.conversation_manager.get_history()
                    turn_index = sum(1 for msg in history if msg.get('role') == 'user')
                except Exception:
                    turn_index = None

                # Use pre-computed radar_result from before yielding final metadata
                # Log both original and corrected responses for comparison
                if 'radar_result' in locals() and radar_result is not None:
                    current_features['radar_evaluation'] = {
                        'scores': radar_result.radar_scores,
                        'reasons': radar_result.radar_reasons,
                        'failing_dimensions': radar_result.failing_dimensions,
                        'was_corrected': radar_result.was_corrected,
                        'rounds_used': radar_result.rounds_used,
                        'original_draft': original_response if 'original_response' in locals() else None,
                        'corrected_response': radar_result.final_response if radar_result.was_corrected else None,
                        'eval_prompt_tokens': getattr(radar_result, 'eval_prompt_tokens', 0),
                        'eval_completion_tokens': getattr(radar_result, 'eval_completion_tokens', 0),
                        'correction_prompt_tokens': getattr(radar_result, 'correction_prompt_tokens', 0),
                        'correction_completion_tokens': getattr(radar_result, 'correction_completion_tokens', 0),
                        'total_radar_tokens': getattr(radar_result, 'total_radar_tokens', 0)
                    }
                    logger.info(
                        f"RADAR logged for streaming: was_corrected={radar_result.was_corrected}, total_tokens={getattr(radar_result, 'total_radar_tokens', 0)}")
                # Save QueryDetails response update
                try:
                    connection = get_connection();
                    query_details = QueryDetails(
                        query_id=query_id,
                        user_query=query,
                        response=collected_answer if 'collected_answer' in locals() else "[STREAM FAILED]",
                        latency_ms=total_latency_ms,
                        is_follow_up=turn_index > 1 if turn_index is not None else False,
                        mode=current_mode,
                        persona=current_persona,
                        llm_latency_ms=llm_latency_ms,
                        search_latency_ms=search_latency_ms,
                        reranker_latency_ms=rerank_latency_ms,
                        sources=cited_sources if 'cited_sources' in locals() else [],
                        features_json=current_features,
                    )
                    connection.save_query_details(query_details)
                    logger.info(f"QueryDetails updated successfully for query_id={query_id}")
                except Exception as exc:
                    logger.error(f"Failed to update QueryDetails for query_id={query_id}: {exc}")

                # Log OpenAI usage
                try:
                    if tt is not None:
                        # Calculate costs

                        rates = get_cost_rates(self.deployment_name)
                        # The rates from get_cost_rates are already per 1M tokens (after being multiplied by 1000)
                        # So we need to divide tokens by 1M to get the correct cost
                        prompt_cost = (pt or 0) * rates["prompt"] / 1000000
                        completion_cost = (ct or 0) * rates["completion"] / 1000000
                        total_cost = prompt_cost + completion_cost
                        open_ai_usage_obj = OpenAIUsage(
                            query_id=query_id,
                            model=self.deployment_name,
                            prompt_tokens=pt or 0,
                            completion_tokens=ct or 0,
                            total_tokens=tt or 0,
                            prompt_cost=prompt_cost,
                            completion_cost=completion_cost,
                            total_cost=total_cost,
                            call_type="chat.completions.stream",
                            scenario='rag_streaming_response',
                            user_id=_get_user_id()
                        )
                        connection.save_openai_usage(open_ai_usage_obj)
                        logger.info(f"OpenAI usage saved successfully for query_id={query_id}")
                    else:
                        logger.warning(f"OpenAI usage not logged due to missing total_tokens for query_id={query_id}")
                except Exception as usage_exc:
                    logger.error(f"Failed to log OpenAI usage for query_id={query_id}: {usage_exc}")

                logger.info(f"Robust logging completed for stream (success={ 'collected_answer' in locals() and len(collected_answer) > 0 })")

            except Exception as final_exc:
                # Absolute last resort to prevent crashing the generator
                logger.critical(f"METRICS_FATAL: Failure in robust logging finally block: {final_exc}")
            
    def clear_conversation_history(self, preserve_system_message: bool = True) -> None:
        """
        Clear the conversation history.
        
        Args:
            preserve_system_message: Whether to preserve the initial system message
        """
        self.conversation_manager.clear_history(preserve_system_message)
        logger.info(f"Conversation history cleared (preserve_system_message={preserve_system_message})")

    def get_persona_setting(self, setting_key: str, default: Any = None) -> Any:
        """
        Get a persona-specific setting value.

        Args:
            setting_key: The key of the setting to retrieve
            default: The default value if the setting is not found
        Returns:
            The setting value or default
        """
        return get_setting_of_persona(setting_key, default,self.settings.get('persona'))
