import sys
import os
import time
import psutil

# Suppress pygame welcome print message to avoid corrupting MCP stdio stream
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcp.server.fastmcp import FastMCP
from services import mission_store

mcp = FastMCP("RealTimeMonitoring")

@mcp.tool()
async def get_system_metrics() -> str:
    """
    Retrieve real-time resource utilization metrics from the host machine
    (CPU usage, memory usage, disk utilization, and active process count).
    """
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        
        # Calculate uptime
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        uptime_str = time.strftime('%H:%M:%S', time.gmtime(uptime_seconds))

        lines = [
            "=== HOST SYSTEM METRICS ===",
            f"CPU Usage: {cpu_percent}%",
            f"Memory Usage: {mem.percent}% ({mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB)",
            f"Disk Usage: {disk.percent}% ({disk.used // (1024**3)}GB used / {disk.total // (1024**3)}GB total)",
            f"System Uptime: {uptime_str}",
            f"Total Active Processes: {len(psutil.pids())}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to retrieve system metrics: {e}"

@mcp.tool()
async def list_recent_missions(limit: int = 10) -> str:
    """
    List the most recent J.A.R.V.I.S execution missions and their current statuses.
    """
    try:
        missions = mission_store.list_missions(limit=limit)
        if not missions:
            return "No missions found in the history database."
            
        lines = ["=== RECENT J.A.R.V.I.S. MISSIONS ==="]
        for m in missions:
            dur = f"{m['duration_ms'] / 1000:.1f}s" if m.get("duration_ms") else "N/A"
            err = f" (Error: {m['error'][:40]})" if m.get("error") else ""
            lines.append(
                f"[{m['id']}] {m['status'].upper()} | {m['title']} | Duration: {dur}{err}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to list recent missions: {e}"

@mcp.tool()
async def get_mission_details(mission_id: str) -> str:
    """
    Get detailed logs, events, and results for a specific J.A.R.V.I.S mission.
    """
    try:
        mission = mission_store.get_mission(mission_id)
        if not mission:
            return f"Mission '{mission_id}' not found."
            
        events = mission_store.get_mission_events(mission_id, limit=30)
        
        lines = [
            f"=== MISSION DETAILS: {mission_id} ===",
            f"Title: {mission['title']}",
            f"Request: {mission['request']}",
            f"Status: {mission['status'].upper()}",
            f"Created At: {mission['created_at']}",
            f"Duration: {mission['duration_ms'] / 1000 if mission.get('duration_ms') else 'N/A'} seconds",
        ]
        if mission.get("final_answer"):
            lines.append(f"Final Answer:\n{mission['final_answer']}")
        if mission.get("error"):
            lines.append(f"Error:\n{mission['error']}")
            
        if events:
            lines.append("\n=== MISSION TIMELINE / EVENTS ===")
            for e in events:
                lines.append(f"[{e['timestamp'][-12:-1]}] {e['source']} - {e['type']} ({e['level'].upper()})")
                
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to retrieve mission details: {e}"

@mcp.tool()
async def check_backend_logs(lines_count: int = 30) -> str:
    """
    Read the latest log lines from the backend-server.log.
    """
    try:
        log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend-server.log"))
        if not os.path.exists(log_path):
            # Check if it's main backend log or uvicorn logs
            log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend", "backend-server.log"))
            if not os.path.exists(log_path):
                return f"Log file not found at {log_path}"
            
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            
        recent_lines = lines[-lines_count:]
        return f"=== LAST {len(recent_lines)} LINES OF BACKEND SERVER LOG ===\n" + "".join(recent_lines)
    except Exception as e:
        return f"Failed to read logs: {e}"

if __name__ == "__main__":
    mcp.run()
