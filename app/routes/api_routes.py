#app/routes/api_routes.py
import io
#=====================================================================================================#
#Copyright (c) 2026 Agilent Technologies All rights reserved worldwide.
#Agilent Confidential, Use is permitted only in accordance with applicable End User License Agreement.
#=====================================================================================================#

import json
import os
import traceback
import urllib

from azure.storage.blob import BlobServiceClient
from flask import Blueprint, jsonify, request, session, Response, redirect, g, stream_with_context, send_file

from app.Connection import get_connection
from app.models.models import Feedback
from app.rag.services.correction_loop import CorrectionLoop
from app.rag.services.groundedness_checker import GroundednessChecker, EvaluationResult
from app.utils.admin_app_util import get_observability_summary, get_experimental_mode_metrics
from app.utils.app_util import clean_session, get_source_doc, custom_base64_decode, remove_host_from_url, get_user_name
from app.utils.mode_config import get_mode_info, set_mode, set_persona, get_persona, \
    set_reasoning_effort, set_verbosity
from app.utils.rag_util import get_rag_assistant, llm_helpee_2xl, llm_helpee, clear_rag_assistant, rag_assistants_last_access


# ============================================================================
# API ROUTES BLUEPRINT
# ============================================================================
api_bp = Blueprint('api', __name__, url_prefix='/api')

import logging

# Configure logger
logger = logging.getLogger(__name__)

# ============================================================================
# SAGE EXPERIMENTAL MODE API ENDPOINTS
# ============================================================================

@api_bp.route('/mode', methods=['GET'])
def api_get_mode():
    """Get current mode and feature configuration for this session."""
    try:
        mode_info = get_mode_info()
        # Include toggle status so frontend knows if experimental mode is available
        mode_info['experimental_toggle_enabled'] = os.getenv('ENABLE_EXPERIMENTAL_MODE_TOGGLE',
                                                             'false').lower() == 'true'
        return jsonify(mode_info)
    except Exception as e:
        logger.error(f"Error in api_get_mode: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/mode', methods=['POST'])
def api_set_mode():
    """Switch between production and experimental mode for this session.

    Request body:
        {"mode": "production" | "experimental"}

    Response:
        {"success": true, "mode": "...", "features": {...}}

    Note: Experimental mode can ONLY be enabled if ENABLE_EXPERIMENTAL_MODE_TOGGLE=true
    """
    try:
        data = request.get_json() or {}
        new_mode = data.get('mode', 'production')

        if new_mode not in ('production', 'experimental'):
            return jsonify({'error': f'Invalid mode: {new_mode}. Must be "production" or "experimental"'}), 400

        # SECURITY: Experimental mode can only be enabled if toggle is visible
        experimental_toggle_enabled = os.getenv('ENABLE_EXPERIMENTAL_MODE_TOGGLE', 'false').lower() == 'true'

        if new_mode == 'experimental' and not experimental_toggle_enabled:
            logger.warning("Attempted to enable experimental mode but toggle is disabled")
            # Force production mode
            new_mode = 'production'
            # Clear any persona - production mode has no personas
            new_persona = None
        else:
            new_persona = data.get('persona')

        # In production mode, ignore persona completely
        if new_mode == 'production':
            new_persona = None

        # Set the mode in session
        success = set_mode(new_mode)
        if not success:
            return jsonify({'error': 'Failed to set mode'}), 500

        # Handle persona only if in experimental mode
        if new_persona and new_mode == 'experimental':
            if not set_persona(new_persona):
                return jsonify({'error': f'Invalid persona: {new_persona}'}), 400
        elif new_mode == 'production':
            # Clear persona - production mode uses environment defaults, not persona config
            session.pop('sage_persona', None)

        # Recreate RAG assistant with new mode/persona settings
        # session_id = session.get('session_id')
        # if session_id:
        #     # In production mode, pass None for persona to use default behavior
        #     persona_for_assistant = new_persona if new_mode == 'experimental' else None
        #     get_rag_assistant(session_id, force_recreate=True, persona=persona_for_assistant)
        #     log_msg = f"Session {session_id} switched to {new_mode} mode"
        #     if new_persona and new_mode == 'experimental':
        #         log_msg += f" with persona {new_persona}"
        #     logger.info(log_msg)

        # Return updated mode info
        mode_info = get_mode_info()
        session_id = session.get('session_id')
        clean_session(session_id)
        mode_info['success'] = True
        mode_info['experimental_toggle_enabled'] = experimental_toggle_enabled

        # Handle reasoning_effort and verbosity overrides
        new_reasoning = data.get('reasoning_effort')
        new_verbosity = data.get('verbosity')
        if new_reasoning:
            if not set_reasoning_effort(new_reasoning):
                logger.warning(f"Invalid reasoning_effort: {new_reasoning}")
            else:
                mode_info['reasoning_effort'] = new_reasoning
        if new_verbosity:
            if not set_verbosity(new_verbosity):
                logger.warning(f"Invalid verbosity: {new_verbosity}")
            else:
                mode_info['verbosity'] = new_verbosity

        return jsonify(mode_info)

    except Exception as e:
        logger.error(f"Error in api_set_mode: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route("/stream_query", methods=["POST"])
def api_stream_query():
    """Stream the assistant's response for a query; emits [[META]] lines for metadata."""
    data = request.get_json()
    user_query = data.get("query", "")
    logger.info(f"Stream query received: {user_query}")
    logger.info(f"DEBUG - Full request payload: {json.dumps(data)}")

    # Robust Persona Sync: Update session persona if provided in request
    client_persona = None
    if "persona" in data:
        client_persona = data["persona"]
        logger.info(f"Stream request specifies persona: {client_persona}")
        try:
            set_persona(client_persona)
        except ImportError:
            logger.warning("Could not import set_persona from mode_config")

    # Sync reasoning_effort and verbosity overrides from request
    if "reasoning_effort" in data:
        set_reasoning_effort(data["reasoning_effort"])
    if "verbosity" in data:
        set_verbosity(data["verbosity"])

    # Get the session ID
    session_id = session.get('session_id')
    if not session_id or session_id not in rag_assistants_last_access.keys():
        session_id = os.urandom(16).hex()
        session['session_id'] = session_id
        logger.info(f"Created new session ID for streaming: {session_id}")

    # Extract any settings from the request
    settings = data.get("settings", {})
    logger.info(f"DEBUG - Request settings: {json.dumps(settings)}")

    def generate():
        try:
            # Get or create the RAG assistant for this session
            rag_assistant = get_rag_assistant(session_id, persona=client_persona)

            # Update settings if provided
            if settings:
                for key, value in settings.items():
                    if hasattr(rag_assistant, key):
                        setattr(rag_assistant, key, value)

                # Enforce supported chat deployment for compatibility
                if "model" in settings:
                    logger.warning("Enforcing 'gpt-4o' as chat deployment for this session")
                    rag_assistant.deployment_name = "gpt-4o"
                    # Sync OpenAIService deployment
                    if hasattr(rag_assistant, "openai_service"):
                        rag_assistant.openai_service.deployment_name = rag_assistant.deployment_name

            logger.info(f"Starting stream response for: {user_query}")
            logger.info(f"DEBUG - Using model: {rag_assistant.deployment_name}")
            logger.info(f"DEBUG - Temperature: {rag_assistant.temperature}")
            logger.info(f"DEBUG - Max tokens: {rag_assistant.max_tokens}")
            logger.info(f"DEBUG - Top P: {rag_assistant.top_p}")

            # Use streaming method
            for chunk in rag_assistant.stream_rag_response(user_query, session_id=session_id):
                logger.debug("DEBUG - AI stream chunk: %s", chunk)
                if isinstance(chunk, str):
                    yield chunk
                else:
                    yield f"\n[[META]]{json.dumps(chunk)}"

            logger.info(f"Completed stream response for: {user_query}")

        except Exception as e:
            logger.error(f"Error in stream_query: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            yield f"Sorry, I encountered an error: {str(e)}"
            yield f"\n[[META]]" + json.dumps({"error": str(e)})
    generated_response = stream_with_context(generate())
    return Response(generated_response, mimetype="text/plain")

@api_bp.route("/welcome_message", methods=["GET"])
def api_welcome_message():
    """
    API endpoint to get a welcome message for the user.
    """
    try:
        user_name = get_user_name(g.user_info)

        welcome_message = f"Welcome, {user_name}. 👋 I’m SAGE, your assistant. Tell me what you’re looking for, and I’ll help you find the information."
        return jsonify({"message": welcome_message})
    except Exception as e:
        logger.error(f"Error generating welcome message: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

# API endpoint for magic button query enhancement
@api_bp.route('/magic_query', methods=['POST'])
def api_magic_query():
    """Takes input_text, runs llm_helpee, returns a one-line enhanced query; 500 on error."""
    data = request.get_json() or {}
    input_text = data.get('input_text', '').strip()
    if not input_text:
        return jsonify({'error': 'Input text cannot be empty'}), 400
    try:
        output = llm_helpee(input_text)
        # Add a flag to indicate this is an enhanced query
        return jsonify({
            'output': output,
            'is_enhanced': True
        })
    except Exception as e:
        logger.error(f"Error in api_magic_query: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@api_bp.route('/magic_query_2xl', methods=['POST'])
def api_magic_query_2xl():
    """Takes input_text, runs llm_helpee_2xl to produce a structured prompt; 500 on error."""
    data = request.get_json() or {}
    input_text = data.get('input_text', '').strip()
    if not input_text:
        return jsonify({'error': 'Input text cannot be empty'}), 400
    try:
        output = llm_helpee_2xl(input_text)
        # Add a flag to indicate this is an enhanced query
        return jsonify({
            'output': output,
            'is_enhanced': True
        })
    except Exception as e:
        logger.error(f"Error in api_magic_query_2xl: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@api_bp.route("/clear_history", methods=["POST"])
def api_clear_history():
    """Clear this session's conversation history; no-op if none exists."""
    session_id = session.get('session_id')
    clean_session(session_id)
    return redirect('/')


@api_bp.route("/feedback", methods=["POST"])
def api_feedback():
    """Persist feedback to disk and database."""
    import os
    import json
    import uuid
    import traceback
    import config

    data = request.get_json()
    logger.debug(f"Received feedback data: {json.dumps(data)}")

    feedback_data = {
        "question": data.get("question", ""),
        "response": data.get("response", ""),
        "feedback_tags": data.get("feedback_tags", []),
        "comment": data.get("comment", ""),
        "evaluation_json": {},
        "query_id": data.get("query_id", None),
        "citations": data.get("citations", [])
    }

    # Log the processed feedback data to help diagnose issues
    logger.debug(f"Processed feedback data: {json.dumps(feedback_data)}")

    # Save feedback to file for persistence
    try:
        feedback_dir = config.FEEDBACK_DIR
        if not os.path.exists(feedback_dir):
            os.makedirs(feedback_dir)
        # Use UUID for unique filename
        filename = f"{uuid.uuid4()}.json"
        filepath = os.path.join(feedback_dir, filename)
        with open(filepath, "w") as f:
            json.dump(feedback_data, f, indent=2)
        logger.info(f"Feedback saved to file: {filepath}")
    except Exception as e:
        logger.error(f"Error saving feedback to file: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")

    try:
        # Save feedback to database
        feedback_obj = Feedback(
            query_id=feedback_data["query_id"] if "query_id" in feedback_data else None,
            feedback_tags=feedback_data["feedback_tags"],
            comments=feedback_data["comment"]
        )
        connection = get_connection()
        feedback_id = connection.save_feedback(feedback_obj)
        logger.info(f"Feedback saved to DB with ID: {feedback_id}")
        return jsonify({"success": True, "feedback_id": feedback_id}), 200
    except Exception as e:
        logger.error(f"Error saving feedback to database: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/transcribe', methods=['POST'])
def api_transcribe():
    """
    Voice-to-text transcription endpoint using Azure OpenAI Whisper.
    Accepts audio file uploads and returns transcribed text.
    """
    try:
        # Check if audio file is present in request
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400

        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({'error': 'No audio file selected'}), 400

        # Validate file type
        allowed_extensions = {'.mp3', '.wav', '.m4a', '.ogg', '.webm'}
        file_ext = os.path.splitext(audio_file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            return jsonify({'error': f'Unsupported audio format. Allowed: {", ".join(allowed_extensions)}'}), 400

        logger.info(
            f"Received audio file for transcription: {audio_file.filename}, size: {len(audio_file.read())} bytes")
        audio_file.seek(0)  # Reset file pointer after reading size

        # Get transcription credentials from environment
        transcription_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT_TRANSCRIPTION")
        transcription_key = os.getenv("AZURE_OPENAI_KEY_TRANSCRIPTION")

        if not transcription_endpoint or not transcription_key:
            logger.error("Missing transcription credentials in environment variables")
            return jsonify({'error': 'Transcription service not configured'}), 500

        logger.info(f"Using transcription endpoint: {transcription_endpoint}")

        # Prepare the request to Azure OpenAI
        import requests

        headers = {
            'Authorization': f'Bearer {transcription_key}',
        }

        # Prepare the file for upload
        files = {
            'file': (audio_file.filename, audio_file.stream, audio_file.content_type)
        }

        data = {
            'model': 'gpt-4o-transcribe'
        }

        logger.info("Sending audio to Azure OpenAI transcription service...")

        # Make the request to Azure OpenAI
        response = requests.post(
            transcription_endpoint,
            headers=headers,
            files=files,
            data=data,
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            transcribed_text = result.get('text', '')

            logger.info(f"Transcription successful: {transcribed_text[:100]}...")

            return jsonify({
                'success': True,
                'text': transcribed_text,
                'language': result.get('language', 'unknown')
            })
        else:
            logger.error(f"Transcription API error: {response.status_code} - {response.text}")
            return jsonify({
                'error': f'Transcription failed: {response.status_code}',
                'details': response.text
            }), response.status_code

    except Exception as e:
        logger.error(f"Error in transcription endpoint: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'error': 'Internal server error during transcription',
            'details': str(e)
        }), 500


@api_bp.route('/download/<base64Url>')
def download_file(base64Url):
    try:
        # Try to get source_path if available with index metadata
        source_url = get_source_doc(base64Url)
        if source_url:
            blob_url = source_url
        # Fallback to get the source path if it is not part of metadata, get it by decoding base64URL
        else:
            # Decode the base64Url back to a string(blob URL)
            blob_url = custom_base64_decode(base64Url)
            logger.debug(f"Decoded base64Url to blob_url: {blob_url[:100]}...")

        # Validate that we have a proper URL before proceeding
        if not blob_url or not blob_url.lower().startswith('http'):
            logger.error(
                f"Failed to decode citation URL. Input: {base64Url[:50]}..., Result: {blob_url[:100] if blob_url else 'None'}")
            return f"Error downloading file: Unable to decode document URL", 400

        # URL decode to clean the URL
        blob_url = urllib.parse.unquote(blob_url)

        # Getting blob name by removing the host details
        blob_path = remove_host_from_url(blob_url)
        logger.debug(f"Extracted blob_path: {blob_path}")

        CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if CONNECTION_STRING:
            CONNECTION_STRING = CONNECTION_STRING.strip('"\'')

        blob_path_parts = blob_path.lstrip("/").split("/", 1)

        # Validate that we have both container name and blob path
        if len(blob_path_parts) < 2 or not blob_path_parts[0] or not blob_path_parts[1]:
            logger.error(
                f"Invalid blob path format. blob_url={blob_url}, blob_path={blob_path}, parts={blob_path_parts}")
            return f"Error downloading file: Invalid document URL format - cannot extract container and blob path from '{blob_path}'", 400

        CONTAINER_NAME = blob_path_parts[0]

        blob_name = blob_path_parts[1]

        blob_service_client = BlobServiceClient.from_connection_string(CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)

        blob_client = container_client.get_blob_client(blob_name)
        blob_data = blob_client.download_blob()

        # Read the content into an in-memory byte stream
        file_content = io.BytesIO()
        blob_data.readinto(file_content)
        file_content.seek(0)  # Reset stream position to the beginning

        # Extract filename from the blob_name
        filename = blob_name.split('/')[-1]

        return send_file(
            file_content,
            mimetype=blob_client.get_blob_properties().content_settings.content_type or 'application/octet-stream',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return f"Error downloading file: {e}", 500


@api_bp.route('/view/<base64Url>')
def view_file_inline(base64Url):
    """Serve source document inline for browser preview (PDF, images, text).
    Same blob-fetching logic as download_file but with as_attachment=False."""
    try:
        source_url = get_source_doc(base64Url)
        if source_url:
            blob_url = source_url
        else:
            blob_url = custom_base64_decode(base64Url)

        if not blob_url or not blob_url.lower().startswith('http'):
            return "Error viewing file: Unable to decode document URL", 400

        blob_url = urllib.parse.unquote(blob_url)
        blob_path = remove_host_from_url(blob_url)

        CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if CONNECTION_STRING:
            CONNECTION_STRING = CONNECTION_STRING.strip('"\'')

        blob_path_parts = blob_path.lstrip("/").split("/", 1)
        if len(blob_path_parts) < 2 or not blob_path_parts[0] or not blob_path_parts[1]:
            return f"Error viewing file: Invalid document URL format", 400

        CONTAINER_NAME = blob_path_parts[0]
        blob_name = blob_path_parts[1]

        blob_service_client = BlobServiceClient.from_connection_string(CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        blob_client = container_client.get_blob_client(blob_name)
        blob_data = blob_client.download_blob()

        file_content = io.BytesIO()
        blob_data.readinto(file_content)
        file_content.seek(0)

        filename = blob_name.split('/')[-1]
        mimetype = blob_client.get_blob_properties().content_settings.content_type or 'application/octet-stream'

        return send_file(
            file_content,
            mimetype=mimetype,
            as_attachment=False,
            download_name=filename
        )
    except Exception as e:
        return f"Error viewing file: {e}", 500


@api_bp.route('/observability/summary')
def api_observability_summary():
    """Return comprehensive observability metrics for the dashboard."""
    from datetime import datetime, timedelta
    try:
        range_param = request.args.get('range', '7d')

        # Calculate date range
        end_date = datetime.now()
        if range_param == '24h':
            start_date = end_date - timedelta(hours=24)
        elif range_param == '7d':
            start_date = end_date - timedelta(days=7)
        elif range_param == '30d':
            start_date = end_date - timedelta(days=30)
        else:  # 'all'
            start_date = None
            end_date = None

        data = get_observability_summary(start_date, end_date)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error in observability API: {e}")
        return jsonify({'error': str(e)}), 500


@api_bp.route('/observability/experimental')
def api_observability_experimental():
    """Return metrics for the Experimental Mode dashboard tab."""
    from datetime import datetime, timedelta
    try:
        range_param = request.args.get('range', '7d')

        # Calculate date range
        end_date = datetime.now()
        if range_param == '24h':
            start_date = end_date - timedelta(hours=24)
        elif range_param == '7d':
            start_date = end_date - timedelta(days=7)
        elif range_param == '30d':
            start_date = end_date - timedelta(days=30)
        else:  # 'all'
            start_date = None
            end_date = None

        data = get_experimental_mode_metrics(start_date, end_date)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error in experimental mode API: {e}")
        return jsonify({'error': str(e)}), 500


@api_bp.route('/verify_groundedness', methods=['POST'])
def api_verify_groundedness():
    """Async groundedness verification for Scientist persona.

    Called after response is streamed to verify claims against sources.
    Returns score, grounded status, and any unsupported claims.

    Request body:
        {"query": "...", "answer": "...", "context": "..."}

    Response:
        {"score": 0.0-1.0, "grounded": bool, "unsupported_claims": [...]}
    """
    try:
        data = request.get_json() or {}
        query = data.get('query', '')
        answer = data.get('answer', '')
        context = data.get('context', '')
        try:
            query_id = int(data.get('query_id', ''))
        except (TypeError, ValueError):
            query_id = None

        if not answer:
            return jsonify({'error': 'Answer is required'}), 400

        # Check if groundedness checker is available
        try:

            # Get current persona for policy selection
            current_persona = get_persona()

            checker = GroundednessChecker.from_env()
            result = checker.evaluate_response(
                query=query,
                answer=answer,
                context=context,
                persona=current_persona,
                query_id=query_id
            )

            return jsonify({
                'score': result.score,
                'grounded': result.grounded,
                'confidence': result.confidence,
                'unsupported_claims': result.unsupported_claims[:5],  # Limit for brevity
                'recommendations': result.recommendations[:3] if result.recommendations else [],
                # Intent fulfillment assessment
                'question_addressed': result.question_addressed,
                'question_addressed_score': result.question_addressed_score,
                'intent_fulfillment': result.intent_fulfillment,
                'intent_fulfillment_score': result.intent_fulfillment_score,
                'intent_gaps': result.intent_gaps[:3] if result.intent_gaps else [],
                # Policy metadata
                'policies_applied': result.policies_applied,
            })

        except ImportError as e:
            logger.warning(f"Groundedness checker not available: {e}")
            # Return neutral result if checker not available
            return jsonify({
                'score': 0.8,  # Neutral-positive default
                'grounded': True,
                'confidence': 0.5,
                'unsupported_claims': [],
                'warning_level': 'none',
                'note': 'Verification service not configured'
            })

    except Exception as e:
        logger.error(f"Error in api_verify_groundedness: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/correct_response', methods=['POST'])
def api_correct_response():
    """Post-stream correction for Scientist persona.

    Called after verification fails to regenerate a grounded response.

    Request body:
        {"query": "...", "draft": "...", "context": "...", "evaluation": {...}, "sources": [...]}

    Response:
        {"corrected_response": "...", "was_corrected": bool, "sources": [...]}
    """
    try:
        data = request.get_json() or {}
        query = data.get('query', '')
        draft = data.get('draft', '')
        context = data.get('context', '')
        evaluation_data = data.get('evaluation', {})
        original_sources = data.get('sources', [])  # Get original sources from request

        if not draft:
            return jsonify({'error': 'Draft response is required'}), 400

        # Only allow for Scientist persona
        current_persona = get_persona()
        if current_persona != 'scientist':
            return jsonify({
                'corrected_response': draft,
                'was_corrected': False,
                'sources': original_sources,
                'note': f'Correction only available for scientist persona (current: {current_persona})'
            })

        try:

            logger.info(f"[CORRECTION] Starting post-stream correction for query: {query[:100]}...")

            # Reconstruct EvaluationResult from the passed data
            evaluation = EvaluationResult(
                grounded=evaluation_data.get('grounded', False),
                score=evaluation_data.get('score', 0.0),
                confidence=evaluation_data.get('confidence', 0.0),
                supported_claims=[],
                unsupported_claims=evaluation_data.get('unsupported_claims', []),
                recommendations=evaluation_data.get('recommendations', []),
                evaluation_summary="Post-stream correction",
                citation_audit={},
                question_addressed=evaluation_data.get('question_addressed', True),
                question_addressed_score=evaluation_data.get('question_addressed_score', 0.0),
                intent_fulfillment=evaluation_data.get('intent_fulfillment', True),
                intent_fulfillment_score=evaluation_data.get('intent_fulfillment_score', 0.0),
                intent_gaps=evaluation_data.get('intent_gaps', []),
                scope_issues=[],
                failure_mode=evaluation_data.get('failure_mode', 'mixed'),
                policies_applied=evaluation_data.get('policies_applied', {})
            )

            # Instantiate correction loop and apply correction
            correction_loop = CorrectionLoop()
            corrected = correction_loop._apply_correction(
                correction_loop._build_correction_prompt(
                    draft=draft,
                    query=query,
                    context=context,
                    evaluation=evaluation
                )
            )

            if corrected and corrected.strip() and corrected != draft:
                logger.info(f"[CORRECTION] Successfully generated corrected response")

                # Re-extract and renumber citations from corrected response
                corrected_response, cited_sources = _extract_and_renumber_citations(
                    corrected, context, original_sources
                )

                return jsonify({
                    'corrected_response': corrected_response,
                    'was_corrected': True,
                    'sources': cited_sources
                })
            else:
                logger.info(f"[CORRECTION] No meaningful correction generated, keeping original")
                return jsonify({
                    'corrected_response': draft,
                    'was_corrected': False,
                    'sources': original_sources,
                    'note': 'Correction did not produce a different response'
                })

        except ImportError as e:
            logger.warning(f"Correction service not available: {e}")
            return jsonify({
                'corrected_response': draft,
                'was_corrected': False,
                'sources': original_sources,
                'error': 'Correction service not available'
            })

    except Exception as e:
        logger.error(f"Error in api_correct_response: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route("/query", methods=["POST"])
def api_query():
    """Submit user query to this session's assistant and return answer + citations."""
    data = request.get_json()
    logger.info("DEBUG - Incoming /api/query payload: %s", json.dumps(data))
    user_query = data.get("query", "")
    is_enhanced = data.get("is_enhanced", False)
    logger.info(f"API query received: {user_query}")

    # Robust Persona Sync: Update session persona if provided in request
    client_persona = None
    if "persona" in data:
        client_persona = data["persona"]
        logger.info(f"Request specifies persona: {client_persona}")
        try:
            from mode_config import set_persona
            set_persona(client_persona)
        except ImportError:
            logger.warning("Could not import set_persona from mode_config")

    # Get the session ID
    session_id = session.get('session_id')
    if not session_id:
        session_id = os.urandom(16).hex()
        session['session_id'] = session_id
        logger.info(f"Created new session ID: {session_id}")

    # Extract any settings from the request
    settings = data.get("settings", {})
    logger.info(f"DEBUG - Request settings: {json.dumps(settings)}")

    try:
        # Get or create the RAG assistant for this session
        rag_assistant = get_rag_assistant(session_id, persona=client_persona)

        # Update settings if provided
        if settings:
            for key, value in settings.items():
                if hasattr(rag_assistant, key):
                    setattr(rag_assistant, key, value)

            # Enforce supported chat deployment for compatibility
            if "model" in settings:
                logger.warning("Enforcing 'gpt-4o' as chat deployment for this session")
                rag_assistant.deployment_name = "gpt-4o"
                # Sync OpenAIService deployment
                if hasattr(rag_assistant, "openai_service"):
                    rag_assistant.openai_service.deployment_name = rag_assistant.deployment_name

        logger.info(f"DEBUG - Using model: {rag_assistant.deployment_name}")
        logger.info(f"DEBUG - Temperature: {rag_assistant.temperature}")
        logger.info(f"DEBUG - Max tokens: {rag_assistant.max_tokens}")
        logger.info(f"DEBUG - Top P: {rag_assistant.top_p}")

        answer, cited_sources, _, evaluation, context = rag_assistant.generate_rag_response(user_query,
                                                                                            is_enhanced=is_enhanced)
        logger.info(f"API query response generated for: {user_query}")
        logger.info(f"DEBUG - Response length: {len(answer)}")
        logger.info(f"DEBUG - Number of cited sources: {len(cited_sources)}")

        # Database logging is now handled within rag_assistant.generate_rag_response
        # to ensure latency and token metrics are captured correctly.

        return jsonify({
            "answer": answer,
            "sources": cited_sources,
            "evaluation": evaluation
        })
    except Exception as e:
        logger.error(f"Error in api_query: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            "error": str(e)
        }), 500