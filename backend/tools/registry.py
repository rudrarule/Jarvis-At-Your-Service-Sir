"""
registry.py — Central Tool Registry for Native Function Calling
Maps tool names → executable functions + JSON schemas for LLM tool calling.
"""
import asyncio
import inspect

from tools.music_tool import play_music
from tools.browser_tool import browser_search, open_url
from tools.weather_tool import get_weather
from tools.file_system_tool import (
    read_file,
    write_file,
    append_file,
    list_directory,
    search_files,
    search_in_files,
)
from tools.system_control_tool import (
    open_app,
    close_app,
    open_folder,
    lock_system,
    shutdown_system,
    restart_system,
    list_running_apps,
)
from tools.whatsapp_tool import (
    whatsapp_briefing,
    whatsapp_unread,
    whatsapp_missed_calls,
    whatsapp_send,
)


# ── Tool Schemas (OpenAI/Ollama format) ───────────────────
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": "Call this tool if the user asks you to play a song. Use the query parameter to specify the exact requested song or artist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The song name, artist, or search query to play on YouTube",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Open a specific website URL directly in a browser window. Use when user says 'open google', 'go to github', 'visit youtube', etc. Navigates directly to the URL without searching.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL to open (e.g., 'https://google.com', 'github.com', 'youtube.com')"
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_search",
            "description": "Search the INTERNET for any topic, question, news, shopping, or general knowledge query. This is the DEFAULT tool for any search or lookup request. Opens a browser with results. Use this for anything the user wants to find online — news, products, people, events, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The specific search query"
                    },
                    "open_visible": {
                        "type": "boolean",
                        "description": "Set to true if user wants to see the browser window. False for background extraction only.",
                        "default": False
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a specific location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city or location (e.g., 'Faridabad', 'New York')",
                    }
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Call this tool to read or open a file. Useful for reading notes, code, or any document data requested by the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The relative path to the file to be read."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Call this tool to write a new file or overwrite an existing file. Useful when the user wants to create a file or save information to disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The path where the file should be created or overwritten."},
                    "content": {"type": "string", "description": "The full content to write to the file."}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "append_file",
            "description": "Call this tool to append text to an existing file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The path to the file to append to."},
                    "content": {"type": "string", "description": "The text to append."}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "Call this tool to list the files and folders inside a given directory. If querying the root workspace, leave the path empty.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The path to list contents of, or an empty string for the root workspace."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for LOCAL files on the user's computer by filename. ONLY use this when the user explicitly asks to find a file on their PC, like 'find my resume file' or 'where is config.json'. Do NOT use for internet/web searches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The substring to look for in the file names."}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_in_files",
            "description": "Search for text INSIDE local workspace files. ONLY use when user asks to find specific code or text within their project files. Do NOT use for internet/web searches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The substring of text to look for inside file contents."}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open a whitelisted application on the system. Use when user says 'open chrome', 'launch vscode', 'start notepad', etc. Only allowed apps: chrome, firefox, edge, vscode, notepad, calc, terminal, explorer, spotify, discord.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "The application name (e.g., 'chrome', 'vscode', 'notepad')"
                    }
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_app",
            "description": "Close a running application by name. Use when user says 'close chrome', 'quit vscode', 'exit notepad', etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "The application name to close (e.g., 'chrome', 'vscode', 'notepad')"
                    }
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_folder",
            "description": "Open a predefined folder in Windows Explorer. Use when user says 'open desktop', 'open downloads', 'open documents', 'open pictures', 'open workspace'. Only allowed folders: desktop, downloads, documents, pictures, workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_name": {
                        "type": "string",
                        "description": "The folder name (e.g., 'desktop', 'downloads', 'documents')"
                    }
                },
                "required": ["folder_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lock_system",
            "description": "Lock the Windows workstation immediately. Use when user says 'lock system', 'lock computer', 'lock screen'.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shutdown_system",
            "description": "Shutdown the system. REQUIRES explicit confirmation. If user says 'shutdown' without confirm, ask for confirmation. Only execute with confirm=True.",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be True to execute shutdown. False = just check/ask."
                    }
                },
                "required": ["confirm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restart_system",
            "description": "Restart the system. REQUIRES explicit confirmation. If user says 'restart' without confirm, ask for confirmation. Only execute with confirm=True.",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be True to execute restart. False = just check/ask."
                    }
                },
                "required": ["confirm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_running_apps",
            "description": "List currently running applications. Use when user asks 'what's open', 'what apps are running', 'list running programs'.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "whatsapp_briefing",
            "description": "Get a full WhatsApp briefing including unread messages and missed calls. Use when user asks 'who messaged me', 'any new messages', 'whatsapp update', 'check my messages', 'any missed calls on whatsapp', 'give me my whatsapp briefing'.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "whatsapp_unread",
            "description": "Get only unread WhatsApp messages. Use when user specifically asks about messages only, like 'any unread messages', 'who texted me'.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "whatsapp_missed_calls",
            "description": "Get missed WhatsApp calls. Use when user asks 'any missed calls', 'who called me'.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "whatsapp_send",
            "description": "Send a WhatsApp message to a contact. Use when user says 'text mom', 'send a whatsapp message to X', 'tell X on whatsapp that Y'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact": {
                        "type": "string",
                        "description": "The contact phone number (e.g., '919876543210') or JID"
                    },
                    "message": {
                        "type": "string",
                        "description": "The message text to send"
                    }
                },
                "required": ["contact", "message"],
            },
        },
    },
]

# ── Function Lookup ───────────────────────────────────────
TOOL_FUNCTIONS = {
    "play_music": play_music,
    "browser_search": browser_search,
    "open_url": open_url,
    "get_weather": get_weather,
    "read_file": read_file,
    "write_file": write_file,
    "append_file": append_file,
    "list_directory": list_directory,
    "search_files": search_files,
    "search_in_files": search_in_files,
    "open_app": open_app,
    "close_app": close_app,
    "open_folder": open_folder,
    "lock_system": lock_system,
    "shutdown_system": shutdown_system,
    "restart_system": restart_system,
    "list_running_apps": list_running_apps,
    "whatsapp_briefing": whatsapp_briefing,
    "whatsapp_unread": whatsapp_unread,
    "whatsapp_missed_calls": whatsapp_missed_calls,
    "whatsapp_send": whatsapp_send,
}

# ── Intent → Tool Group Mapping ──────────────────────────
# Each intent from the classifier maps to a small set of relevant tools.
# This lets the router model see only 2-3 schemas instead of all 17.
TOOL_GROUPS = {
    "MUSIC":    ["play_music"],
    "SEARCH":   ["browser_search"],
    "OPEN_URL": ["open_url"],
    "APP":      ["open_app", "close_app", "list_running_apps"],
    "FOLDER":   ["open_folder"],
    "SYSTEM":   ["lock_system", "shutdown_system", "restart_system", "list_running_apps"],
    "FILE":     ["read_file", "write_file", "append_file", "list_directory", "search_files", "search_in_files"],
    "WEATHER":  ["get_weather"],
    "WHATSAPP": ["whatsapp_briefing", "whatsapp_unread", "whatsapp_missed_calls", "whatsapp_send"],
}

# Build a name→schema lookup for fast pruning
_SCHEMA_BY_NAME = {s["function"]["name"]: s for s in TOOL_SCHEMAS}


def get_schemas_for_intent(intent: str) -> list[dict]:
    """Return only the tool schemas relevant to a classified intent."""
    tool_names = TOOL_GROUPS.get(intent, [])
    return [_SCHEMA_BY_NAME[name] for name in tool_names if name in _SCHEMA_BY_NAME]


def _sanitize_arguments(func, arguments: dict) -> dict:
    """Filter out invalid arguments and cast boolean strings."""
    sig = inspect.signature(func)
    valid_keys = sig.parameters.keys()
    sanitized = {}
    for k, v in arguments.items():
        if k in valid_keys:
            if isinstance(v, str):
                if v.lower() == 'true':
                    v = True
                elif v.lower() == 'false':
                    v = False
            sanitized[k] = v
    return sanitized


async def execute_tool(tool_name: str, arguments: dict) -> str:
    """
    Look up and execute a tool by name.
    Handles both sync and async tool functions.
    Returns a Jarvis-style confirmation string.
    """
    func = TOOL_FUNCTIONS.get(tool_name)
    if not func:
        return f"I'm sorry, sir. I don't recognize the tool '{tool_name}'."

    try:
        sanitized_args = _sanitize_arguments(func, arguments)
        
        # Check if function is async
        if inspect.iscoroutinefunction(func):
            result = await func(**sanitized_args)
        else:
            result = func(**sanitized_args)

        # play_music returns (title, url)
        if tool_name == "play_music":
            title, url = result
            if url:
                return f"Certainly, sir. Playing {title} on YouTube now."
            else:
                return "I apologize, sir. I couldn't find that song on YouTube."

        # Browser, URL opener, Weather, file system, WhatsApp, and system control tools return formatted strings
        file_system_tools = ["read_file", "write_file", "append_file", "list_directory", "search_files", "search_in_files"]
        system_control_tools = ["open_app", "close_app", "open_folder", "lock_system", "shutdown_system", "restart_system", "list_running_apps"]
        whatsapp_tools = ["whatsapp_briefing", "whatsapp_unread", "whatsapp_missed_calls", "whatsapp_send"]
        
        if tool_name in ["browser_search", "open_url", "get_weather"] + file_system_tools + system_control_tools + whatsapp_tools:
            if isinstance(result, dict):
                import json
                return json.dumps(result, indent=2)
            return result

        if isinstance(result, dict):
            import json
            return json.dumps(result, indent=2)
            
        # Generic fallback for future tools
        return str(result)

    except Exception as e:
        print(f"[TOOL ERROR] Tool execution error ({tool_name}): {e}")
        return f"I encountered an error executing {tool_name}, sir."
