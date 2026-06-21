"""Multi-provider LLM model factory for the llm-wiki project.

Supports: AWS Bedrock, Azure OpenAI, Google Gemini, Anthropic Claude, Ollama, OpenAI.
Priority order matches deep_research/model_factory.py.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the llm-wiki project root
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)


def _get_ssl_verify() -> bool | str:
    """Return SSL verify setting: True, False, or a CA bundle path."""
    verify = os.getenv("VERIFY_SSL", "true").lower()
    if verify in ("false", "0", "no"):
        return False
    for env_var in ("SSL_CAINFO", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        ca = os.getenv(env_var)
        if ca:
            return ca
    return True


def get_configured_model():
    """Build the first matching chat model from the environment configuration.

    Provider priority (highest → lowest):
      1. AWS Bedrock (via OpenAI-compatible endpoint)
      2. Azure OpenAI (with explicit API version)
      3. Azure OpenAI (simple, via ChatOpenAI)
      4. Google Gemini
      5. Anthropic Claude
      6. OpenAI
      7. Ollama (local)

    Returns a LangChain chat model instance ready for ``create_deep_agent``.
    Raises ``ValueError`` when no provider is configured.
    """
    verify_ssl = _get_ssl_verify()

    # ── 1. AWS Bedrock (OpenAI-compatible) ────────────────────────────────────
    if (
            os.getenv("AWS_BEDROCK_ENDPOINT")
            and os.getenv("AWS_BEARER_TOKEN_BEDROCK")
            and os.getenv("MODEL_NAME")
    ):
        import httpx
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr

        return ChatOpenAI(
            base_url=os.environ["AWS_BEDROCK_ENDPOINT"],
            api_key=SecretStr(os.environ["AWS_BEARER_TOKEN_BEDROCK"]),
            model=os.environ["MODEL_NAME"],
            http_client=httpx.Client(verify=verify_ssl),
            stream_usage=True,
        )

    # ── 2. Azure OpenAI (explicit API version → AzureChatOpenAI) ─────────────
    if (
            os.getenv("AZURE_OPENAI_ENDPOINT")
            and os.getenv("AZURE_OPENAI_DEPLOYMENT")
            and os.getenv("AZURE_OPENAI_API_KEY")
            and os.getenv("AZURE_OPENAI_API_VERSION")
    ):
        import httpx
        from langchain_openai import AzureChatOpenAI
        from pydantic import SecretStr

        return AzureChatOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            api_version=os.environ["AZURE_OPENAI_API_VERSION"],
            api_key=SecretStr(os.environ["AZURE_OPENAI_API_KEY"]),
            http_client=httpx.Client(verify=verify_ssl),
            stream_usage=True,
        )

    # ── 3. Azure OpenAI (simple → ChatOpenAI with base_url) ──────────────────
    if (
            os.getenv("AZURE_OPENAI_ENDPOINT")
            and os.getenv("AZURE_OPENAI_DEPLOYMENT")
            and os.getenv("AZURE_OPENAI_API_KEY")
    ):
        import httpx
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr

        return ChatOpenAI(
            base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=SecretStr(os.environ["AZURE_OPENAI_API_KEY"]),
            model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            http_client=httpx.Client(verify=verify_ssl),
            stream_usage=True,
        )

    # ── 4. Google Gemini ──────────────────────────────────────────────────────
    if os.getenv("GOOGLE_API_KEY") and os.getenv("MODEL_NAME"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs = {
            "model": os.environ["MODEL_NAME"],
            "temperature": 0.0,
            "streaming": True,
        }

        if verify_ssl is not True:
            import httpx
            from google import genai
            kwargs["client"] = genai.Client(
                api_key=os.environ["GOOGLE_API_KEY"],
                http_options={"httpx_client": httpx.Client(verify=verify_ssl)},
            )

        return ChatGoogleGenerativeAI(**kwargs)

    # ── 5. Anthropic Claude ───────────────────────────────────────────────────
    if os.getenv("ANTHROPIC_API_KEY") and os.getenv("MODEL_NAME"):
        import httpx
        from langchain.chat_models import init_chat_model

        return init_chat_model(
            model=f"anthropic:{os.environ['MODEL_NAME']}",
            temperature=0.0,
            http_client=httpx.Client(verify=verify_ssl),
        )

    # ── 6. OpenAI ─────────────────────────────────────────────────────────────
    if os.getenv("OPENAI_API_KEY") and os.getenv("MODEL_NAME"):
        import httpx
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr

        return ChatOpenAI(
            model=os.environ["MODEL_NAME"],
            api_key=SecretStr(os.environ["OPENAI_API_KEY"]),
            http_client=httpx.Client(verify=verify_ssl),
            stream_usage=True,
        )

    # ── 7. Ollama (local) ─────────────────────────────────────────────────────
    if os.getenv("OLLAMA_API_BASE") and os.getenv("MODEL_NAME"):
        from langchain.chat_models import init_chat_model

        return init_chat_model(
            model=f"ollama:{os.environ['MODEL_NAME']}",
            base_url=os.environ["OLLAMA_API_BASE"],
            temperature=0.0,
        )

    raise ValueError(
        "No LLM provider configured. Set environment variables for at least one provider:\n"
        "  - AWS Bedrock:       AWS_BEDROCK_ENDPOINT + AWS_BEARER_TOKEN_BEDROCK + MODEL_NAME\n"
        "  - Azure OpenAI:      AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_DEPLOYMENT + AZURE_OPENAI_API_KEY\n"
        "  - Google Gemini:     GOOGLE_API_KEY + MODEL_NAME\n"
        "  - Anthropic Claude:  ANTHROPIC_API_KEY + MODEL_NAME\n"
        "  - OpenAI:            OPENAI_API_KEY + MODEL_NAME\n"
        "  - Ollama (local):    OLLAMA_API_BASE + MODEL_NAME\n"
    )
