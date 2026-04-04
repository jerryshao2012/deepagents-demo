"""Shared model configuration for the deep research project."""

from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv
from pydantic import SecretStr

from utils import get_ssl_verify_config

# Load environment variables
load_dotenv()


def get_configured_model():
    """Build the first matching chat model from environment configuration."""
    verify_ssl = get_ssl_verify_config()

    if os.getenv("GOOGLE_API_KEY") and os.getenv("MODEL_NAME"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=os.getenv("MODEL_NAME", "gemini-3-pro-preview"),
            temperature=0.0,
        )

    if os.getenv("ANTHROPIC_API_KEY") and os.getenv("MODEL_NAME"):
        from langchain.chat_models import init_chat_model

        return init_chat_model(
            model=os.getenv("MODEL_NAME", "anthropic:claude-sonnet-4-5"),
            temperature=0.0,
        )

    if os.getenv("OLLAMA_API_BASE") and os.getenv("MODEL_NAME"):
        from langchain.chat_models import init_chat_model

        return init_chat_model(
            model=f"ollama:{os.getenv('MODEL_NAME')}",
            base_url=os.getenv("OLLAMA_API_BASE"),
        )

    if (
            os.getenv("AZURE_OPENAI_ENDPOINT")
            and os.getenv("AZURE_OPENAI_DEPLOYMENT")
            and os.getenv("AZURE_OPENAI_API_KEY")
            and os.getenv("AZURE_OPENAI_API_VERSION")
    ):
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
            api_key=SecretStr(os.getenv("AZURE_OPENAI_API_KEY", "")),
            http_client=httpx.Client(verify=verify_ssl),
        )

    raise ValueError("No model found. Please set up a model")
