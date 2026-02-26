"""
OpenAIService class for handling interactions with the Azure OpenAI API
"""
import logging
import os

from openai import AzureOpenAI

from app.Connection import get_connection
from app.models.models import OpenAIUsage
from app.utils.app_util import _get_user_id
from app.utils.openai_logger import log_openai_call
from config import get_cost_rates

logger = logging.getLogger(__name__)

class OpenAIService:
    """
    Handles interactions with the Azure OpenAI API.
    
    This class is responsible for:
    - Initializing the Azure OpenAI client
    - Sending requests to the API
    - Processing responses
    - Error handling and logging
    """
    
    def __init__(self, azure_endpoint=None, api_key=None, api_version="2024-02-01", deployment_name=None):
        """
        Initialize the OpenAI service.
        
        Args:
            azure_endpoint: The Azure OpenAI endpoint URL
            api_key: The API key for authentication
            api_version: The API version to use
            deployment_name: The deployment name to use for chat completions
        """
        self.azure_endpoint = azure_endpoint
        self.api_key = api_key
        self.api_version = api_version
        self.deployment_name = deployment_name
        
        # Initialize the OpenAI client
        self.client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            api_version=api_version
        )
        
        logger.debug(f"OpenAIService initialized with endpoint: {azure_endpoint}, api_version: {api_version}, deployment: {self.deployment_name}")
    
    def get_chat_response(
        self,
        messages,
        temperature=0.3,
        max_tokens=1000,
        max_completion_tokens=None,
        top_p=1.0,
        presence_penalty=0.0,
        frequency_penalty=0.0,
        response_format=None,
        return_usage=False,
        model=None,
        query_id=None,
        scenario=None,
        # GPT-5 specific parameters
        reasoning_effort=None,
        verbosity=None,
        user_id=None
    ):
        """
        Get a response from the OpenAI chat completions API.
        """
        effective_model = model if model else self.deployment_name
        
        logger.info(f"Sending request to OpenAI with {len(messages)} messages (model: {effective_model})")
        
        # Prepare request parameters
        is_gpt5_family = effective_model and effective_model.lower().startswith('gpt-5')
        
        request = {
            'model': effective_model,
            'messages': messages,
            'presence_penalty': presence_penalty,
            'frequency_penalty': frequency_penalty
        }
        
        if is_gpt5_family:
            request['max_completion_tokens'] = max_completion_tokens if max_completion_tokens is not None else max_tokens
            if reasoning_effort:
                request['reasoning_effort'] = reasoning_effort
            if verbosity:
                request['verbosity'] = verbosity
        else:
            request['temperature'] = temperature
            request['top_p'] = top_p
            if max_completion_tokens is not None:
                request['max_completion_tokens'] = max_completion_tokens
            else:
                request['max_tokens'] = max_tokens
        
        if response_format:
            request['response_format'] = response_format

        try:
            # Send the request
            response = self.client.chat.completions.create(**request)
            
            # Log the API call
            log_openai_call(request, response)
            
            # Extract usage
            usage = response.usage
            prompt_tokens = usage.prompt_tokens if usage else None
            completion_tokens = usage.completion_tokens if usage else None
            total_tokens = usage.total_tokens if usage else None

            # Calculate costs

            rates = get_cost_rates(effective_model)
            # The rates from get_cost_rates are already per 1M tokens (after being multiplied by 1000)
            # So we need to divide tokens by 1M to get the correct cost
            prompt_cost = (prompt_tokens or 0) * rates["prompt"] / 1000000
            completion_cost = (completion_tokens or 0) * rates["completion"] / 1000000
            total_cost = prompt_cost + completion_cost
            if not user_id:
                user_id = _get_user_id()
            open_ai_usage_obj = OpenAIUsage(
                query_id=query_id,
                model=effective_model,
                prompt_tokens=prompt_tokens or 0,
                completion_tokens=completion_tokens or 0,
                total_tokens=total_tokens or 0,
                prompt_cost=prompt_cost,
                completion_cost=completion_cost,
                total_cost=total_cost,
                call_type="chat.completions",
                scenario=scenario,
                user_id=user_id
            )
            connection = get_connection()
            connection.save_openai_usage(open_ai_usage_obj)
            logger.info(f"OpenAI usage saved successfully for query_id={query_id}")
            
            answer = response.choices[0].message.content or ""
            
            if return_usage:
                return answer, {
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens,
                    'total_tokens': total_tokens
                }
            return answer
            
        except Exception as e:
            logger.error(f"Error calling OpenAI API: {e}")
            raise

    def get_responses_api_response(
        self,
        messages,
        reasoning_effort='high',
        verbosity='high',
        max_tokens=2000,
        return_usage=False,
        model=None,
        query_id=None,
        scenario=None,
        api_version='2025-03-01-preview',
    ):
        """
        Get a response using the OpenAI Responses API (for Scientist persona).
        
        The Responses API provides native support for reasoning effort and verbosity
        parameters that aren't available in the Chat Completions API.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
                     Note: 'system' role should be 'developer' for Responses API
            reasoning_effort: 'low', 'medium', or 'high' (default: 'high')
            verbosity: 'low', 'medium', or 'high' (default: 'high')
            max_tokens: Maximum tokens for the response
            return_usage: If True, return (text, usage_dict) tuple
            model: Model deployment name (uses self.deployment_name if None)
            query_id: Query ID for logging
            scenario: Scenario name for logging
            api_version: API version (must be 2025-03-01-preview or later)
            
        Returns:
            The response text, or tuple (text, usage) if return_usage=True
        """
        effective_model = model if model else self.deployment_name
        
        logger.info(f"[RESPONSES API] Sending request with reasoning_effort={reasoning_effort}, verbosity={verbosity}")
        
        try:
            # Create a client with the Responses API version
            responses_client = AzureOpenAI(
                azure_endpoint=self.azure_endpoint,
                api_key=self.api_key,
                api_version=api_version
            )
            
            # Convert messages: 'system' -> 'developer' for Responses API
            input_messages = []
            for msg in messages:
                role = msg['role']
                if role == 'system':
                    role = 'developer'  # Responses API uses 'developer' instead of 'system'
                input_messages.append({'role': role, 'content': msg['content']})
            
            request = {
                'model': effective_model,
                'input': input_messages,
                'reasoning': {'effort': reasoning_effort},
                'text': {
                    'format': {'type': 'text'},
                    'verbosity': verbosity
                }
            }
            
            response = responses_client.responses.create(**request)
            
            # Extract text from response
            output_text = self._extract_responses_api_text(response)
            
            # Log the API call
            log_openai_call(request, response)
            
            # Extract usage info
            usage = response.usage
            input_tokens = getattr(usage, 'input_tokens', 0) if usage else 0
            output_tokens = getattr(usage, 'output_tokens', 0) if usage else 0
            reasoning_tokens = 0
            if usage and hasattr(usage, 'output_tokens_details'):
                details = usage.output_tokens_details
                if details and hasattr(details, 'reasoning_tokens'):
                    reasoning_tokens = details.reasoning_tokens or 0
            
            total_tokens = input_tokens + output_tokens

            # Calculate costs

            rates = get_cost_rates(effective_model)
            # The rates from get_cost_rates are already per 1M tokens (after being multiplied by 1000)
            # So we need to divide tokens by 1M to get the correct cost
            prompt_cost = (input_tokens or 0) * rates["prompt"] / 1000000
            completion_cost = (output_tokens or 0) * rates["completion"] / 1000000
            total_cost = prompt_cost + completion_cost

            try:
                open_ai_usage_obj = OpenAIUsage(
                    query_id=query_id,
                    model=effective_model,
                    prompt_tokens=input_tokens or 0,
                    completion_tokens=output_tokens or 0,
                    total_tokens=total_tokens or 0,
                    prompt_cost=prompt_cost,
                    completion_cost=completion_cost,
                    total_cost=total_cost,
                    call_type="responses.create",
                    scenario=scenario,
                    user_id=_get_user_id()
                )
                connection = get_connection()
                connection.save_openai_usage(open_ai_usage_obj)
                logger.info(f"OpenAI usage saved successfully for query_id={query_id}")
            except Exception as save_exc:
                logger.warning(f"Failed to save OpenAI usage: {save_exc}")


            logger.info(f"[RESPONSES API] Received response (length: {len(output_text)}, reasoning_tokens: {reasoning_tokens})")
            
            if return_usage:
                usage_dict = {
                    'prompt_tokens': input_tokens,
                    'completion_tokens': output_tokens,
                    'total_tokens': total_tokens,
                    'reasoning_tokens': reasoning_tokens
                }
                return output_text, usage_dict
            
            return output_text
            
        except Exception as e:
            logger.error(f"[RESPONSES API] Error: {e}", exc_info=True)
            raise

    def _extract_responses_api_text(self, response):
        """Safely extract text content from a Responses API response."""
        # Try output_text convenience property first
        if hasattr(response, 'output_text') and response.output_text:
            return response.output_text
        
        # Otherwise iterate through output items
        output_text = ""
        if hasattr(response, 'output') and response.output:
            for item in response.output:
                if hasattr(item, 'content') and item.content is not None:
                    for content in item.content:
                        if hasattr(content, 'text') and content.text:
                            output_text += content.text
                elif hasattr(item, 'text') and item.text:
                    output_text += item.text
        
        return output_text

    def stream_responses_api(
        self,
        messages,
        reasoning_effort='high',
        verbosity='high',
        model=None,
        api_version='2025-03-01-preview',
    ):
        """
        Stream a response using the OpenAI Responses API (for Scientist persona).
        
        Yields text chunks as they arrive from the API.
        
        Args:
            messages: List of message dictionaries
            reasoning_effort: 'low', 'medium', or 'high'
            verbosity: 'low', 'medium', or 'high'
            model: Model deployment name
            api_version: API version for Responses API
            
        Yields:
            Text chunks from the streaming response
        """
        effective_model = model if model else self.deployment_name
        
        logger.info(f"[RESPONSES API STREAM] Starting stream with reasoning_effort={reasoning_effort}, verbosity={verbosity}")
        
        # Create a client with the Responses API version
        responses_client = AzureOpenAI(
            azure_endpoint=self.azure_endpoint,
            api_key=self.api_key,
            api_version=api_version
        )
        
        # Convert messages: 'system' -> 'developer' for Responses API
        input_messages = []
        for msg in messages:
            role = msg['role']
            if role == 'system':
                role = 'developer'
            input_messages.append({'role': role, 'content': msg['content']})
        
        request = {
            'model': effective_model,
            'input': input_messages,
            'reasoning': {'effort': reasoning_effort},
            'text': {
                'format': {'type': 'text'},
                'verbosity': verbosity
            },
            'stream': True
        }
        
        try:
            stream = responses_client.responses.create(**request)
            
            collected_text = ""
            usage_info = None
            
            for event in stream:
                # Handle different event types in the stream
                if hasattr(event, 'type'):
                    if event.type == 'response.output_text.delta':
                        # Text chunk
                        delta = getattr(event, 'delta', '')
                        if delta:
                            collected_text += delta
                            yield delta
                    elif event.type == 'response.completed':
                        # Final event with usage info
                        if hasattr(event, 'response') and hasattr(event.response, 'usage'):
                            usage_info = event.response.usage
                elif hasattr(event, 'delta'):
                    # Alternative delta format
                    delta = event.delta
                    if delta:
                        collected_text += delta
                        yield delta
            
            # Yield usage info at the end as a dict (will be detected by caller)
            if usage_info:
                input_tokens = getattr(usage_info, 'input_tokens', 0) or 0
                output_tokens = getattr(usage_info, 'output_tokens', 0) or 0
                reasoning_tokens = 0
                if hasattr(usage_info, 'output_tokens_details'):
                    details = usage_info.output_tokens_details
                    if details and hasattr(details, 'reasoning_tokens'):
                        reasoning_tokens = details.reasoning_tokens or 0
                total_tokens = input_tokens + output_tokens

                logger.info(
                    f"[RESPONSES API STREAM] Complete. Total: {len(collected_text)} chars, tokens: {total_tokens}")

                # Yield usage dict for caller to capture
                yield {
                    '__usage__': True,
                    'prompt_tokens': input_tokens,
                    'completion_tokens': output_tokens,
                    'total_tokens': total_tokens,
                    'reasoning_tokens': reasoning_tokens
                }
                
        except Exception as e:
            logger.error(f"[RESPONSES API STREAM] Error: {e}", exc_info=True)
            raise

    def get_chat_response_stream(
        self,
        messages,
        temperature=0.3,
        max_tokens=1000,
        max_completion_tokens=None,
        top_p=1.0,
        presence_penalty=0.0,
        frequency_penalty=0.0,
        model=None,
        # GPT-5 specific parameters
        reasoning_effort=None,
        verbosity=None,
    ):
        """
        Get a streaming response from the OpenAI chat completions API.
        """
        effective_model = model if model else self.deployment_name
        is_gpt5_family = effective_model and effective_model.lower().startswith('gpt-5')
        
        request = {
            'model': effective_model,
            'messages': messages,
            'stream': True,
            'stream_options': {"include_usage": True},
            'presence_penalty': presence_penalty,
            'frequency_penalty': frequency_penalty
        }
        
        if is_gpt5_family:
            request['max_completion_tokens'] = max_completion_tokens if max_completion_tokens is not None else max_tokens
            if reasoning_effort:
                request['reasoning_effort'] = reasoning_effort
            if verbosity:
                request['verbosity'] = verbosity
        else:
            request['temperature'] = temperature
            request['top_p'] = top_p
            if max_completion_tokens is not None:
                request['max_completion_tokens'] = max_completion_tokens
            else:
                request['max_tokens'] = max_tokens

        try:
            return self.client.chat.completions.create(**request)
        except Exception as e:
            logger.error(f"Error starting OpenAI stream: {e}")
            raise

    def get_embedding(self, text, model=None):
        """
        Get embedding for the provided text.
        """
        try:
            effective_model = model if model else "text-embedding-3-small" # placeholder if not set
            response = self.client.embeddings.create(
                model=effective_model,
                input=text.strip()
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None
        
    def llm_helpee(self, message, scenario) -> str:
        """
        To store the OpenAiUsage for Enhance Query and Detailed Prompt
        
        :param self: Description
        :param message: Description
        """
        open_ai_model = os.getenv("AZURE_OPENAI_MODEL")
        response  = self.client.chat.completions.create(
            model=open_ai_model,
            messages=message
        )

        answer = response.choices[0].message.content
        usage = getattr(response, "usage", None)

        prompt_tokens = completion_tokens = total_tokens = None
        if usage is not None:
            try:
                prompt_tokens = getattr(usage, "prompt_tokens", None) if not isinstance(usage, dict) else usage.get(
                    "prompt_tokens")
                completion_tokens = getattr(usage, "completion_tokens", None) if not isinstance(usage, dict) else usage.get(
                    "completion_tokens")
                total_tokens = getattr(usage, "total_tokens", None) if not isinstance(usage, dict) else usage.get(
                    "total_tokens")
            except Exception:
                pass
        
        rates = get_cost_rates(open_ai_model)

        # The rates from get_cost_rates are already per 1M tokens (after being multiplied by 1000)
        # So we need to divide tokens by 1M to get the correct cost
        prompt_cost = (prompt_tokens or 0) * rates["prompt"] / 1000000
        completion_cost = (completion_tokens or 0) * rates["completion"] / 1000000
        total_cost = prompt_cost + completion_cost

        try:
            open_ai_usage_obj = OpenAIUsage(
                query_id=None,
                model=open_ai_model,
                prompt_tokens=prompt_tokens or 0,
                completion_tokens=completion_tokens or 0,
                total_tokens=total_tokens or 0,
                prompt_cost=prompt_cost,
                completion_cost=completion_cost,
                total_cost=total_cost,
                call_type="chat.completions",
                scenario=scenario,
                user_id=_get_user_id()
            )
            connection = get_connection()
            connection.save_openai_usage(open_ai_usage_obj)
            logger.info(f"OpenAI usage saved successfully in DB for user_id={_get_user_id()}")
            logger.info(
            f"OpenAI usage logged to DB: {{'prompt_tokens': {prompt_tokens}, 'completion_tokens': {completion_tokens}, 'total_tokens': {total_tokens}}}")
        except Exception as db_exc:
            logger.warning(f"Failed to save OpenAI usage in DB: {db_exc}")

        return answer
        

