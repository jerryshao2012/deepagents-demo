"""Shared model configuration for the deep research project."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from azure.identity import ManagedIdentityCredential, get_bearer_token_provider
from dotenv import load_dotenv, dotenv_values
from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings
from langgraph.checkpoint.memory import InMemorySaver
from langgraph_checkpoint_cosmosdb import CosmosDBSaver
from pydantic import SecretStr

from logger_utils import setup_logger
from retry_utils import wrap_model_with_rate_limiting
from utils import get_ssl_verify_config

logger = setup_logger(__name__)


def create_config():
    # Load environment variables from .env file
    env_path = Path(__file__) / '.env'
    if env_path.exists():
        load_dotenv(env_path, override=True)
        # Get all environment variables from .env file
        env_vars = dotenv_values(env_path)
        logger.info(f"Loaded {len(env_vars)} environment variables from {env_path}")
    else:
        logger.warning(f".env file not found at {env_path}")
        env_vars = {}
    config = {}

    # Add all environment variables to config
    for key, value in env_vars.items():
        config[key] = value
        logger.info(f"Added to config: {key}")
    logger.info(f"Config created with {len(config)} total items")
    return config


def get_openai_auth_kwargs() -> dict:
    """Return the authentication kwargs for Azure OpenAI clients.

    Reads ``AZURE_AUTH_TYPE`` from the environment:
      * ``"managed_identity"`` → returns ``azure_ad_token_provider``
      * anything else (default ``"api_key"``) → returns ``api_key``
    """
    if os.getenv("AZURE_AUTH_TYPE") == "managed_identity":
        logger.info("Using Managed Identity for Azure OpenAI authentication.")
        credential = ManagedIdentityCredential(
            client_id=os.environ.get("AZURE_CLIENT_ID")
        )
        token_provider = get_bearer_token_provider(
            credential, os.environ["AZURE_OPENAI_SCOPE"]
        )
        return {"azure_ad_token_provider": token_provider}
    else:
        # default: os.getenv("AZURE_AUTH_TYPE") == "api_key"
        logger.info("Using API Key for Azure OpenAI authentication.")
        return {"api_key": SecretStr(os.getenv("AZURE_OPENAI_API_KEY", ""))}


def create_embedding_model():
    """Create an Azure OpenAI embedding model instance."""
    return init_embeddings(
        model=f"azure_openai:{os.environ['AZURE_EMBEDDING_NAME']}",
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_deployment=os.environ["AZURE_EMBEDDING_DEPLOYMENT_NAME"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        **get_openai_auth_kwargs(),
    )


def create_memory_saver():
    # Initialize memory checkpointer for conversation state
    memory_type = os.environ["MEMORY_TYPE"]
    if memory_type == 'memory':
        return InMemorySaver()
    elif memory_type == 'cosmosdb':
        return CosmosDBSaver(
            database_name=os.environ["COSMOSDB_DB_NAME"],
            container_name=os.environ["COSMOSDB_CONTAINER_NAME"]
        )
    else:
        logger.error(f"Unsupported MEMORY_TYPE: {memory_type}")
        raise ValueError(f"Unsupported MEMORY_TYPE: {memory_type}")


def get_configured_model():
    """Build the first matching chat model from the environment configuration with rate limit retry."""
    verify_ssl = get_ssl_verify_config()

    if os.getenv("GOOGLE_API_KEY") and os.getenv("MODEL_NAME"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = ChatGoogleGenerativeAI(
            model=os.getenv("MODEL_NAME", "gemini-3-pro-preview"),
            temperature=0.0,
        )
        return wrap_model_with_rate_limiting(model)

    if os.getenv("ANTHROPIC_API_KEY") and os.getenv("MODEL_NAME"):
        model = init_chat_model(
            model=f"anthropic:{os.getenv("MODEL_NAME", "claude-sonnet-4-5-20250929")}",
            temperature=0.0,
        )
        return wrap_model_with_rate_limiting(model)

    if os.getenv("OLLAMA_API_BASE") and os.getenv("MODEL_NAME"):
        model = init_chat_model(
            model=f"ollama:{os.getenv('MODEL_NAME')}",
            base_url=os.getenv("OLLAMA_API_BASE"),
            temperature=0.0,
        )
        return wrap_model_with_rate_limiting(model)

    if (
            os.getenv("AZURE_OPENAI_ENDPOINT")
            and os.getenv("AZURE_OPENAI_DEPLOYMENT")
            and (os.getenv("AZURE_OPENAI_API_KEY")
                 or (os.getenv("AZURE_CLIENT_ID") and os.getenv("AZURE_OPENAI_SCOPE")))
            and os.getenv("AZURE_OPENAI_API_VERSION")
    ):
        from langchain_openai import AzureChatOpenAI

        model = AzureChatOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
            http_client=httpx.Client(verify=verify_ssl),
            stream_usage=True,
            temperature=0.0,
            **get_openai_auth_kwargs(),
        )
        return wrap_model_with_rate_limiting(model)

    raise ValueError("No model found. Please set up a model")
