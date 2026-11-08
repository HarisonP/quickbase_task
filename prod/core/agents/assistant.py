"""A minimal chat agent with no tools."""

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langfuse.langchain import CallbackHandler
from langgraph.graph.state import CompiledStateGraph

SYSTEM_PROMPT = "You are a helpful assistant. Keep your answers short and clear."


def build_assistant(model: BaseChatModel) -> CompiledStateGraph:
    agent = create_agent(model=model, tools=[], system_prompt=SYSTEM_PROMPT)
    # Bound into the agent's config, so every run of this agent is traced in Langfuse.
    return agent.with_config({"callbacks": [CallbackHandler()]})
