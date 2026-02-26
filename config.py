import os
from dotenv import load_dotenv
load_dotenv()

# Load environment variables from .env file
# This is useful for local development
# OpenAI Configuration
OPENAI_ENDPOINT = os.getenv("OPENAI_ENDPOINT", os.getenv("AZURE_OPENAI_ENDPOINT"))
OPENAI_KEY = os.getenv("OPENAI_KEY", os.getenv("AZURE_OPENAI_KEY"))
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", os.getenv("AZURE_OPENAI_KEY"))
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION", os.getenv("AZURE_OPENAI_API_VERSION"))
# Azure OpenAI Deployment Names
EMBEDDING_DEPLOYMENT = os.getenv("EMBEDDING_DEPLOYMENT", os.getenv("AZURE_OPENAI_EMBEDDING_NAME"))
CHAT_DEPLOYMENT = os.getenv("CHAT_DEPLOYMENT", os.getenv("AZURE_OPENAI_MODEL"))
# Normalize unsupported model names: remove any gpt-5 config at configuration load
if CHAT_DEPLOYMENT and isinstance(CHAT_DEPLOYMENT, str) and "gpt-5" in CHAT_DEPLOYMENT.lower():
    CHAT_DEPLOYMENT = "gpt-4o"

# Azure Cognitive Search Configuration
SEARCH_ENDPOINT = os.getenv("SEARCH_ENDPOINT", os.getenv("AZURE_SEARCH_SERVICE"))
SEARCH_INDEX = os.getenv("SEARCH_INDEX", os.getenv("AZURE_SEARCH_INDEX"))
SEARCH_KEY = os.getenv("SEARCH_KEY", os.getenv("AZURE_SEARCH_KEY"))
VECTOR_FIELD = os.getenv("VECTOR_FIELD")
# Logging Configuration
LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s - %(levelname)s - %(message)s")
LOG_FILE = os.getenv("LOG_FILE", "app.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
# Feedback Configuration
FEEDBACK_DIR = os.getenv("FEEDBACK_DIR", "feedback_data")
FEEDBACK_FILE = os.getenv("FEEDBACK_FILE", "feedback.json") 
# Searches for .env file in the current directory or parent directories
# This is useful for local development
# --- Database Configuration ---
# Get database credentials from environment variables loaded from .env
# Provide default values if needed, though .env should ideally contain them
POSTGRES_HOST = os.getenv("POSTGRES_HOST", os.getenv("PGHOST", "localhost")) # Look for POSTGRES_HOST
POSTGRES_PORT = os.getenv("POSTGRES_PORT", os.getenv("PGPORT", "5432"))      # Look for POSTGRES_PORT
POSTGRES_DB = os.getenv("POSTGRES_DB", os.getenv("PGDATABASE", "postgres"))      # Look for POSTGRES_DB
POSTGRES_USER = os.getenv("POSTGRES_USER", os.getenv("PGUSER", "postgres"))    # Look for POSTGRES_USER
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", os.getenv("PGPASSWORD"))        # Look for POSTGRES_PASSWORD

POSTGRES_SSL_MODE = os.getenv("POSTGRES_SSL_MODE", os.getenv("PGSSLMODE", "require")) # Default to 'require' for Render

AES_KEY = os.getenv("AES_KEY")

# -------- Environment-Aware Model Validation --------
# Prevent accidental use of production models in dev/local environments
def _validate_production_model_usage():
    """
    Validate that production models are not being used in dev/local environments.
    Raises a RuntimeError if a production model is detected in a non-production environment.
    
    Detection logic:
    - If Azure-specific environment variables are present (WEBSITE_SITE_NAME, WEBSITES_PORT),
      we're running in Azure App Service → allow production models
    - If these variables are NOT set, we're running locally → block production models
    """
    # Detect if running in Azure App Service
    # Azure automatically sets these variables when running in the cloud
    is_azure_environment = (
        os.getenv("WEBSITE_SITE_NAME") is not None or 
        os.getenv("WEBSITES_PORT") is not None or
        os.getenv("WEBSITE_INSTANCE_ID") is not None
    )
    
    # If running in Azure, allow production models
    if is_azure_environment:
        return
    
    # List of model variables to check
    model_variables = {
        "AZURE_OPENAI_MODEL": os.getenv("AZURE_OPENAI_MODEL"),
        "CHAT_DEPLOYMENT": os.getenv("CHAT_DEPLOYMENT"),
        "CHAT_DEPLOYMENT_GPT_5": os.getenv("CHAT_DEPLOYMENT_GPT_5"),
        "AZURE_OPENAI_CHAT_COMPLETION_DEPLOYED_MODEL_NAME": os.getenv("AZURE_OPENAI_CHAT_COMPLETION_DEPLOYED_MODEL_NAME"),
        "RERANKER_MODEL": os.getenv("RERANKER_MODEL"),
    }
    
    # Check each model variable for production suffix
    production_models_detected = []
    for var_name, var_value in model_variables.items():
        if var_value and isinstance(var_value, str) and var_value.endswith("-prod"):
            production_models_detected.append(f"{var_name}={var_value}")
    
    # Raise error if production models are detected
    if production_models_detected:
        error_message = (
            f"\n{'='*80}\n"
            f"🚨 PRODUCTION MODEL DETECTED IN LOCAL ENVIRONMENT 🚨\n"
            f"{'='*80}\n"
            f"Environment: Local/Dev (Azure env vars not detected)\n"
            f"Production models detected:\n"
        )
        for model in production_models_detected:
            error_message += f"  - {model}\n"
        error_message += (
            f"\nTo fix this:\n"
            f"1. Update your .env file to use development models (e.g., gpt-4o-local)\n"
            f"2. Production models are only allowed when running in Azure App Service\n"
            f"   (detected via WEBSITE_SITE_NAME or WEBSITES_PORT environment variables)\n"
            f"{'='*80}\n"
        )
        raise RuntimeError(error_message)

# Run validation when config is loaded
_validate_production_model_usage()

def get_cost_rates(model: str) -> dict:
    """
    Get cost rates for a model.
    First checks environment variables, then falls back to known model pricing.
    Rates are per 1M tokens.
    """
    # Known model pricing (per 1M tokens) - fallback when env vars not set
    # Source: Azure OpenAI / OpenAI pricing pages
    MODEL_PRICING = {
        # GPT-5.2 (high-end agentic model) 
        "gpt-5.2": {"prompt": 1.75, "completion": 14.00, "cached": 0.175},
        "gpt-5.2-local": {"prompt": 1.75, "completion": 14.00, "cached": 0.175},
        "gpt-5.2-dev": {"prompt": 1.75, "completion": 14.00, "cached": 0.175},
        "gpt-5.2-prod": {"prompt": 1.75, "completion": 14.00, "cached": 0.175},
        
        # GPT-4o (standard pricing)
        "gpt-4o": {"prompt": 2.50, "completion": 10.00, "cached": 1.25},
        "gpt-4o-local": {"prompt": 2.50, "completion": 10.00, "cached": 1.25},
        "gpt-4o-dev": {"prompt": 2.50, "completion": 10.00, "cached": 1.25},
        "gpt-4o-prod": {"prompt": 2.50, "completion": 10.00, "cached": 1.25},
        
        # GPT-4o-mini (budget option)
        "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60, "cached": 0.075},
        "gpt-4o-mini-local": {"prompt": 0.15, "completion": 0.60, "cached": 0.075},
        "gpt-4o-mini-dev": {"prompt": 0.15, "completion": 0.60, "cached": 0.075},
        "gpt-4o-mini-prod": {"prompt": 0.15, "completion": 0.60, "cached": 0.075},
        
        # O1 reasoning models
        "o1": {"prompt": 15.00, "completion": 60.00, "cached": 7.50},
        "o1-mini": {"prompt": 1.10, "completion": 4.40, "cached": 0.55},
        "o1-preview": {"prompt": 15.00, "completion": 60.00, "cached": 7.50},
        
        # Legacy models
        "gpt-4-turbo": {"prompt": 10.00, "completion": 30.00, "cached": 5.00},
        "gpt-4": {"prompt": 30.00, "completion": 60.00, "cached": 15.00},
        "gpt-35-turbo": {"prompt": 0.50, "completion": 1.50, "cached": 0.25},
    }
    
    model_lower = model.lower() if model else ""
    model_upper = model.upper() if model else ""

    # First try environment variables
    try:
        prompt_rate = float(os.getenv(f"{model_upper}_PROMPT_COST_PER_1M"))
    except (ValueError, TypeError):
        prompt_rate = None

    if prompt_rate is None:
        try:
            prompt_rate = float(os.getenv(f"{model_upper}_PROMPT_COST_PER_1K"))
        except (ValueError, TypeError):
            prompt_rate = None

    try:
        completion_rate = float(os.getenv(f"{model_upper}_COMPLETION_COST_PER_1M"))
    except (ValueError, TypeError):
        completion_rate = None

    if completion_rate is None:
        try:
            completion_rate = float(os.getenv(f"{model_upper}_COMPLETION_COST_PER_1K"))
        except (ValueError, TypeError):
            completion_rate = None

    # If env vars not set, use fallback pricing
    if prompt_rate is None or completion_rate is None:
        # Try exact match first
        if model_lower in MODEL_PRICING:
            fallback = MODEL_PRICING[model_lower]
            prompt_rate = prompt_rate if prompt_rate is not None else fallback["prompt"]
            completion_rate = completion_rate if completion_rate is not None else fallback["completion"]
        else:
            # Try partial match (e.g., "gpt-5.2-local" → "gpt-5.2")
            for key in MODEL_PRICING:
                if model_lower.startswith(key) or key in model_lower:
                    fallback = MODEL_PRICING[key]
                    prompt_rate = prompt_rate if prompt_rate is not None else fallback["prompt"]
                    completion_rate = completion_rate if completion_rate is not None else fallback["completion"]
                    break
    
    # Default to 0 if still not found
    prompt_rate = prompt_rate if prompt_rate is not None else 0.0
    completion_rate = completion_rate if completion_rate is not None else 0.0

    return {"prompt": prompt_rate, "completion": completion_rate}


def get_current_model() -> str:
    """Get the current chat model deployment name."""
    return os.getenv("CHAT_DEPLOYMENT", os.getenv("AZURE_OPENAI_MODEL", "unknown"))

