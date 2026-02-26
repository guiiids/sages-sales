import datetime
import logging
import os
import traceback

from flask import jsonify, g
from openai import AzureOpenAI

from app.Connection import get_connection
from app.models.models import UserSessions
from app.rag.openai_service import OpenAIService
from app.rag.rag_assistant import FlaskRAGAssistantWithHistory
from app.utils.mode_config import get_mode, get_setting
from config import get_cost_rates
import time

# Configure logger
logger = logging.getLogger(__name__)

# Dictionary to store RAG assistant instances by session ID
rag_assistants = {}

#Disctionary to store RAG assistant last access timestamp by session ID
rag_assistants_last_access = {}

openai_service = OpenAIService(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
)

# Function to get or create a RAG assistant for a session
def get_rag_assistant(session_id, persona=None, force_recreate=False):
    """Get or create a RAG assistant for the given session ID.

    Args:
        session_id: The session ID to get/create assistant for
        force_recreate: If True, recreate the assistant (used after mode switch)
    """

    # Update last access time for TTL tracking
    rag_assistants_last_access[session_id] = time.time()

    # Force recreate assistant if requested (e.g., after mode switch)
    if force_recreate and session_id in rag_assistants:
        logger.info(f"Force recreating RAG assistant for session {session_id} (mode switch)")
        rag_assistants.pop(session_id, None)  # Use pop with default to avoid KeyError in race conditions

    # Update persona for existing assistant if provided
    if session_id in rag_assistants and persona:
        rag_assistants[session_id].settings['persona'] = persona

    if session_id not in rag_assistants:
        connection = get_connection()

        logger.info(f"Saving session {session_id} to DB.")
        user = g.user_info
        print("-------", user)
        user_session = UserSessions(
            session_id=session_id,
            user_id=user['user_id'],
            session_start_timestamp=datetime.datetime.now(),
        )
        user_session = connection.save_user_session(user_session)
        logger.info("User session saved to DB.")

        current_mode = get_mode()
        logger.info(f"Creating new RAG assistant for session {session_id} in {current_mode} mode")

        # Build settings based on current mode
        settings = {
            'model': get_setting('AZURE_OPENAI_MODEL'),
            'temperature': float(get_setting('TEMPERATURE', '0.3')),
            'max_tokens': int(get_setting('CHAT_MAX_TOKENS', os.getenv('MAX_TOKENS', '1000'))),
            'persona': persona,
            'user_session': user_session
        }
        logger.info(f"RAG assistant settings for {current_mode} mode: {settings}")

        rag_assistants[session_id] = FlaskRAGAssistantWithHistory(settings=settings)

        #Created a new assistant instance for the session, saving session in DB
        logger.info(f"RAG assistant instance created for session {session_id}")
    return rag_assistants[session_id]


# LLM helpee helpers
PROMPT_ENHANCER_SYSTEM_MESSAGE = QUERY_ENHANCER_SYSTEM_PROMPT = """
You enhance raw end‑user questions before they go to a Retrieval‑Augmented Generation
search over an enterprise tech‑support knowledge base.

Rewrite the user's input into one concise, information‑dense query that maximises recall
while preserving intent.

Guidelines
• Keep all meaningful keywords; expand abbreviations (e.g. "OLS" → "OpenLab Software"),
  spell out error codes, add product codenames, versions, OS names, and known synonyms.
• Remove greetings, filler, personal data, profanity, or mention of the assistant.
• Infer implicit context (platform, language, API, UI area) when strongly suggested and
  state it explicitly.
• Never ask follow‑up questions. Even if the prompt is vague, make a best‑effort guess
  using typical support context.

Output format
Return exactly one line of plain text—no markdown, no extra keys:
"<your reformulated query>"

Examples
###
User: Why won't ilab let me log in?
→ iLab Operations Software login failure Azure AD SSO authentication error troubleshooting
###
User: Printer firmware bug?
→ printer firmware bug troubleshooting latest firmware update failure printhead model unspecified
###
"""

PROMPT_ENHANCER_SYSTEM_MESSAGE_2XL = """
IDENTITY and PURPOSE

You are an expert Prompt Engineer. Your task is to rewrite a short user query into a detailed, structured prompt that will guide another AI to generate a comprehensive, high-quality answer.

CORE TRANSFORMATION PRINCIPLES

1.  **Assign a Persona:** Start by assigning a relevant expert persona to the AI (e.g., "You are an expert in...").
2.  **State the Goal:** Clearly define the primary task, often as a request for a step-by-step guide or detailed explanation.
3.  **Deconstruct the Task:** Break the user's request into a numbered list of specific instructions for the AI. This should guide the structure of the final answer.
4.  **Enrich with Context:** Anticipate the user's needs by including relevant keywords, potential sub-topics, examples, or common issues that the user didn't explicitly mention.
5.  **Define the Format:** Specify the desired output format, such as Markdown, bullet points, or a professional tone, to ensure clarity and readability.

**Example of a successful transformation:**
- **Initial Query:** `troubleshooting Agilent gc`
- **Resulting Enhanced Prompt:** A detailed, multi-step markdown prompt that begins "You are an expert in troubleshooting Agilent Gas Chromatography (GC) systems..."

STEPS

1.  Carefully analyze the user's query provided in the INPUT section.
2.  Apply the CORE TRANSFORMATION PRINCIPLES to reformulate it into a comprehensive new prompt.
3.  Generate the enhanced prompt as the final output.

OUTPUT INSTRUCTIONS

- Output only the new, enhanced prompt.
- Do not include any other commentary, headers, or explanations.
- The output must be in clean, human-readable Markdown format.

INPUT

The following is the prompt you will improve: user-query
"""


def llm_helpee(input_text: str) -> str:
    """
    Sends PROMPT_ENHANCER_SYSTEM_MESSAGE to the Azure OpenAI model, logs usage into helpee_logs, and returns the AI output.
    """    

    message = [
            {"role": "system", "content": PROMPT_ENHANCER_SYSTEM_MESSAGE},
            {"role": "user", "content": input_text}
    ]

    answer = openai_service.llm_helpee(message, "magic_query_enhancement")

    return answer


def llm_helpee_2xl(input_text: str) -> str:
    """
    Sends PROMPT_ENHANCER_SYSTEM_MESSAGE_2XL to the Azure OpenAI model, logs usage into helpee_logs, and returns the AI output.
    """

    message = [
        {"role": "system", "content": PROMPT_ENHANCER_SYSTEM_MESSAGE_2XL},
        {"role": "user", "content": input_text}
    ]

    answer = openai_service.llm_helpee(message, "magic_query_2xl_enhancement")

    return answer

# Clear RAG assistant for a session
def clear_rag_assistant(session_id):
    """Clears the RAG assistant for the given session ID."""
    try:
        if session_id and session_id in rag_assistants:
            logger.info(f"Clearing conversation history for session {session_id}")
            rag_assistants[session_id].clear_conversation_history()
            return jsonify({"success": True})
        else:
            logger.warning(f"No active session found to clear history")
            return jsonify({"success": True, "message": "No active session found"})
    except Exception as e:
        logger.error(f"Error clearing conversation history: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500