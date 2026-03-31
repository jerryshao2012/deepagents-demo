"""Research Agent - Standalone script for LangGraph deployment.

This module creates a deep research agent with custom tools and prompts
for conducting web research with strategic thinking and context management.
"""
import os
from datetime import datetime

from deepagents import create_deep_agent, SubAgent
from dotenv import load_dotenv

from research_agent.prompts import (
    RESEARCHER_INSTRUCTIONS,
    RESEARCH_WORKFLOW_INSTRUCTIONS,
    SUBAGENT_DELEGATION_INSTRUCTIONS,
)
from research_agent.tools import tavily_search, think_tool, read_pdf_folder, generate_slide_markup
from utils import get_ssl_verify_config

# Load environment variables
load_dotenv()

# Create SSL verification setting - CLI flag takes precedence over env var
verify_ssl = get_ssl_verify_config()

# Limits
max_concurrent_research_units = 3
max_researcher_iterations = 3

# Get current date
current_date = datetime.now().strftime("%Y-%m-%d")

# Combine orchestrator instructions (RESEARCHER_INSTRUCTIONS only for sub-agents)
INSTRUCTIONS = (
        RESEARCH_WORKFLOW_INSTRUCTIONS
        + "\n\n"
        + "=" * 80
        + "\n\n"
        + SUBAGENT_DELEGATION_INSTRUCTIONS.format(
    max_concurrent_research_units=max_concurrent_research_units,
    max_researcher_iterations=max_researcher_iterations)
)

# Create research sub-agent
research_sub_agent: SubAgent = {
    "name": "research-agent",
    "description": "Delegate research to the sub-agent researcher. Only give this researcher one topic at a time.",
    "system_prompt": RESEARCHER_INSTRUCTIONS.format(date=current_date),
    "tools": [tavily_search, think_tool],
}

model = None
# Model Gemini 3
if os.getenv("GOOGLE_API_KEY"):
    from langchain_google_genai import ChatGoogleGenerativeAI

    model = ChatGoogleGenerativeAI(model=os.getenv("MODEL_NAME", "gemini-3-pro-preview"), temperature=0.0)

# Model Claude 4.5
if os.getenv("ANTHROPIC_API_KEY"):
    from langchain.chat_models import init_chat_model

    model = init_chat_model(model=os.getenv("MODEL_NAME", "anthropic:claude-sonnet-4-5-20250929"), temperature=0.0)

# Using Ollama (Local)
if os.getenv("OLLAMA_API_BASE"):
    from langchain.chat_models import init_chat_model

    model = init_chat_model(model=f"ollama:{os.getenv("MODEL_NAME")}", base_url=os.getenv("OLLAMA_API_BASE"))

# Using AzureOpenAI
if os.getenv("AZURE_OPENAI_API_KEY"):
    import httpx
    from langchain_openai import AzureChatOpenAI

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    subscription_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION")

    model = AzureChatOpenAI(
        azure_endpoint=endpoint,
        azure_deployment=deployment,
        api_version=api_version,
        api_key=subscription_key,
        http_client=httpx.Client(verify=verify_ssl)  # Enable/Disable SSL verification for httpx
    )

if model:
    # Create the agent
    agent = create_deep_agent(
        model=model,
        tools=[tavily_search, think_tool, read_pdf_folder, generate_slide_markup],
        system_prompt=INSTRUCTIONS,
        subagents=[research_sub_agent],
    )
else:
    raise ValueError("No model found. Please set up a model")
