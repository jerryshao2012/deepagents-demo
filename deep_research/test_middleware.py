from typing import TypedDict, Any

from langchain.agents.middleware import AgentMiddleware


class ResearchState(TypedDict):
    pass


class CLIInstructionMiddleware(AgentMiddleware[ResearchState, Any, Any]):
    pass


print(CLIInstructionMiddleware().state_schema)
