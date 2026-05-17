"""
master_graph.py — Master LangGraph ReAct Agent with Vision
Builds a StateGraph with LLM caching, MemorySaver checkpointing,
tool error recovery, Llama hallucination interception,
and vision-guided browser observation via screenshots.
"""
import re
import json
import uuid
import os
import copy
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langchain_aws import ChatBedrockConverse

from workflows.tool_wrapper import ALL_TOOLS

# ── LLM Instance Cache ────────────────────────────────────
# Avoids re-instantiating ChatBedrockConverse on every graph iteration.
# Each unique model_id gets one cached instance.
_llm_cache: dict[str, ChatBedrockConverse] = {}


def _clone_message(msg: BaseMessage) -> BaseMessage:
    """Clone messages before vision cleanup so checkpoints/history are not mutated."""
    if hasattr(msg, "model_copy"):
        return msg.model_copy(deep=True)
    if hasattr(msg, "copy"):
        return msg.copy(deep=True)
    return copy.deepcopy(msg)

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

# ── Vision Post-Processor ─────────────────────────────────
def _extract_screenshot_from_tool_results(messages: list[BaseMessage]) -> str | None:
    """
    Scans the most recent ToolMessage for a screenshot_base64 field.
    If found, extracts and returns it (removing it from the text payload
    to avoid sending a giant base64 blob as text to the LLM).
    """
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            content = msg.content
            
            # ToolNode may serialize as str or keep as dict
            data = None
            if isinstance(content, str) and "screenshot_base64" in content:
                try:
                    data = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    pass
            elif isinstance(content, dict):
                data = content
            
            if not data:
                break
                
            # Deep search for the screenshot key
            screenshot = None
            if isinstance(data, dict):
                screenshot = data.get("screenshot_base64")
                if not screenshot and isinstance(data.get("data"), dict):
                    screenshot = data["data"].get("screenshot_base64")
            
            if screenshot and len(screenshot) > 100:  # sanity check: real b64 is large
                # Remove screenshot from text to save tokens
                def _strip_screenshot(d):
                    if isinstance(d, dict):
                        for k in list(d.keys()):
                            if k == "screenshot_base64":
                                d[k] = "[SCREENSHOT - sent as image]"
                            elif isinstance(d[k], dict):
                                _strip_screenshot(d[k])
                
                _strip_screenshot(data)
                
                if isinstance(content, str):
                    msg.content = json.dumps(data)
                else:
                    msg.content = data
                
                print(f"[Vision] Extracted screenshot from tool result ({len(screenshot)} chars base64)")
                return screenshot
            
            break  # Only check the most recent ToolMessage
    return None

def _prune_old_images(messages: list[BaseMessage], keep_count: int = 2):
    """
    Finds all messages with image blocks and keeps only the most recent N.
    Strips image blocks from older messages to satisfy model limits (e.g. 3-image limit).
    """
    image_indices = []
    for i, msg in enumerate(messages):
        if hasattr(msg, "content") and isinstance(msg.content, list):
            if any(isinstance(block, dict) and block.get("type") == "image" for block in msg.content):
                image_indices.append(i)
    
    if len(image_indices) > keep_count:
        to_prune = image_indices[:-keep_count]
        for idx in to_prune:
            msg = messages[idx]
            # Replace list content with just the text part
            text_blocks = [b for b in msg.content if isinstance(b, dict) and b.get("type") == "text"]
            # Join text blocks or keep as list
            msg.content = text_blocks
            print(f"[Vision] Pruned old image from history at index {idx}")

# ── Graph Builder ─────────────────────────────────────────
def build_master_graph():
    """Compiles the ReAct StateGraph with LLM caching, vision, and error resilience."""
    
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
        
        messages = [_clone_message(m) for m in state['messages']]
        updated_messages_for_state = []
        
        # 2. Vision Check: If history has images, we MUST use a vision-capable model
        vision_model_id = os.getenv("CLAUDE_MODEL_ID", "us.meta.llama4-maverick-17b-instruct-v1:0")
        has_images = False
        for m in messages:
            if hasattr(m, "content") and isinstance(m.content, list):
                if any(isinstance(block, dict) and block.get("type") == "image" for block in m.content):
                    has_images = True
                    break
        
        if has_images and model_id != vision_model_id:
            print(f"[Vision] Sticky Vision: History contains images, forcing {vision_model_id}")
            model_id = vision_model_id

        # 3. Cached LLM instance
        llm = _get_llm(model_id, region)
        bound_llm = llm.bind_tools(ALL_TOOLS)
        
        # 4. Prune old images to stay under model limits (e.g. Bedrock max 3)
        _prune_old_images(messages, keep_count=2)
        
        # 5. Iteration tracking
        iteration = state.get("iteration", 0) + 1
        print(f"[Graph] Iteration: {iteration}")
        
        # 5. Vision: Extract screenshot from the latest tool result
        screenshot_b64 = _extract_screenshot_from_tool_results(messages)
        if screenshot_b64:
            # Re-bind to vision model if we just found a new screenshot
            if model_id != vision_model_id:
                model_id = vision_model_id
                llm = _get_llm(model_id, region)
                bound_llm = llm.bind_tools(ALL_TOOLS)
            
            # Inject multimodal content DIRECTLY into the ToolMessage to satisfy Bedrock's turn rules.
            # Find the most recent ToolMessage
            for msg in reversed(messages):
                if isinstance(msg, ToolMessage):
                    original_text = msg.content
                    msg.content = [
                        {"type": "text", "text": str(original_text)},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64
                            }
                        }
                    ]
                    print(f"[Vision] Injected screenshot into ToolMessage -> using {model_id}")
                    # CRITICAL: We must return the stripped ToolMessage to the state
                    # so LangGraph's add_messages can update the original message in history
                    # and prevent base64 bloat in future turns.
                    updated_messages_for_state.append(msg)
                    break
        
        response = await bound_llm.ainvoke(messages)
        
        # 5. Llama Tool Call Interceptor (catches ALL hallucination formats)
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
                    
        return {"messages": updated_messages_for_state + [response], "iteration": iteration}
        
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
