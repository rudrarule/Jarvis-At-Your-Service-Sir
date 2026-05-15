"""
master_graph.py — Master LangGraph ReAct Agent
Builds a StateGraph with LLM caching, MemorySaver checkpointing,
tool error recovery, and Llama hallucination interception.
"""
import re
import json
import uuid
import os
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langchain_aws import ChatBedrockConverse

from workflows.tool_wrapper import ALL_TOOLS

# ── LLM Instance Cache ────────────────────────────────────
# Avoids re-instantiating ChatBedrockConverse on every graph iteration.
# Each unique model_id gets one cached instance.
_llm_cache: dict[str, ChatBedrockConverse] = {}

def _get_llm(model_id: str, region: str) -> ChatBedrockConverse:
    """Returns a cached LLM instance, creating one if needed."""
    if model_id not in _llm_cache:
        _llm_cache[model_id] = ChatBedrockConverse(
            model=model_id,
            region_name=region,
            max_tokens=1024,
            temperature=0.3
        )
        print(f"[Graph] Created new LLM instance: {model_id}")
    else:
        print(f"[Graph] Reusing cached LLM: {model_id}")
    return _llm_cache[model_id]

# ── State Schema ──────────────────────────────────────────
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int  # Accurate iteration counter

# ── Graph Edges ───────────────────────────────────────────
def should_continue(state: AgentState):
    """Determine whether to route to tools or end the conversation."""
    messages = state['messages']
    last_message = messages[-1]
    
    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return END
    return "tools"

# ── Graph Builder ─────────────────────────────────────────
def build_master_graph():
    """Compiles the ReAct StateGraph with LLM caching and error resilience."""
    
    # ToolNode with error recovery — tool exceptions are sent back to the LLM
    # as error messages instead of crashing the entire graph
    tool_node = ToolNode(ALL_TOOLS, handle_tool_errors=True)
    
    async def call_model(state: AgentState, config: RunnableConfig):
        # 1. Dynamic Model Routing via config
        model_id = config.get("configurable", {}).get(
            "model_id", 
            os.getenv("CLAUDE_MODEL_ID", "meta.llama3-3-70b-instruct-v1:0")
        )
        region = os.getenv("AWS_BEDROCK_REGION", "us-east-1")
        
        # 2. Cached LLM instance
        llm = _get_llm(model_id, region)
        bound_llm = llm.bind_tools(ALL_TOOLS)
        
        messages = state['messages']
        
        # 3. Iteration tracking
        iteration = state.get("iteration", 0) + 1
        print(f"[Graph] Iteration: {iteration}")
        
        response = await bound_llm.ainvoke(messages)
        
        # 4. Llama Tool Call Interceptor (catches ALL hallucination formats)
        #    Llama outputs tool calls inconsistently:
        #      Format A: {"name": "browser_observe", "parameters": {}}
        #      Format B: browser_observe()
        #      Format C: browser_interact(element_id=5, action="click")
        #    We catch all of them and convert to native LangChain ToolCalls.
        if not response.tool_calls and isinstance(response.content, str):
            tool_names = [t.name for t in ALL_TOOLS]
            parsed_calls = []
            
            # Strategy 1: JSON format {"name": "...", "parameters": {...}}
            json_matches = re.findall(
                r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"parameters"\s*:\s*(\{[^}]*\})\s*\}',
                response.content
            )
            for name, params_str in json_matches:
                if name in tool_names:
                    try:
                        args = json.loads(params_str)
                        parsed_calls.append({"name": name, "args": args})
                    except json.JSONDecodeError:
                        pass
            
            # Strategy 2: Python-style function calls: tool_name(arg=val, ...)
            if not parsed_calls:
                pattern = r'(' + '|'.join(re.escape(n) for n in tool_names) + r')\s*\(([^)]*)\)'
                py_matches = re.findall(pattern, response.content)
                for name, args_str in py_matches:
                    args = {}
                    if args_str.strip():
                        kv_pairs = re.findall(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\d+))', args_str)
                        for key, str_val, str_val2, int_val in kv_pairs:
                            if int_val:
                                args[key] = int(int_val)
                            else:
                                args[key] = str_val or str_val2
                    parsed_calls.append({"name": name, "args": args})
            
            # Apply only the FIRST parsed call to enforce step-by-step ReAct loop
            if parsed_calls:
                call = parsed_calls[0]
                response.tool_calls.append({
                    "name": call["name"],
                    "args": call["args"],
                    "id": f"call_{uuid.uuid4().hex[:10]}"
                })
                print(f"[Interceptor] Parsed tool call: {call['name']}({call['args']})")
                if len(parsed_calls) > 1:
                    print(f"[Interceptor] Ignored {len(parsed_calls) - 1} additional tool calls to enforce sequential observation.")
                
                # Bedrock Converse API forbids text + tool_calls in the same message
                response.content = ""
                    
        return {"messages": [response], "iteration": iteration}
        
    # Build Graph
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue, ["tools", END])
    workflow.add_edge("tools", "agent")
    
    # Compile with MemorySaver for conversation persistence across sessions
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    return app

# Singleton graph instance
# NOTE: Single-user system. Concurrent requests share the same browser session.
master_graph_app = build_master_graph()
