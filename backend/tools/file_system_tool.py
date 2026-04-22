import os

# ── Sandbox Configuration ─────────────────────────────────────
# Bound all operations to the 'workspace' directory at the root of the project.
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "workspace"))
ALLOWED_EXTENSIONS = {".txt", ".md", ".json", ".py"}
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB
MAX_READ_CHARS = 10000  # Truncate large files to prevent context cutoff

# Ensure the sandbox directory exists immediately upon loading
os.makedirs(BASE_DIR, exist_ok=True)


# ── Utility / Security Layer ──────────────────────────────────
def validate_path(requested_path: str, check_extension: bool = True) -> str:
    """
    Normalizes the path, prevents directory traversal, and ensures 
    it strictly resides within the BASE_DIR sandbox.
    Returns the absolute safe path, or raises a ValueError.
    """
    # Reject explicit traversal attempts quickly
    if ".." in requested_path:
        raise ValueError("Path traversal ('..') is strictly prohibited.")

    # Convert to absolute path
    abs_path = os.path.abspath(requested_path)

    # Ensure it resides inside BASE_DIR
    if not abs_path.startswith(BASE_DIR):
        raise ValueError(f"Access denied. Path must be inside the secure workspace: {BASE_DIR}")
        
    if check_extension and os.path.basename(abs_path):
        # We only check extension if it looks like a filename (has an extension)
        _, ext = os.path.splitext(abs_path)
        if ext and ext.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Access denied. Allowed file types are: {', '.join(ALLOWED_EXTENSIONS)}. Requested: {ext}")

    return abs_path


def safe_join(base: str, path: str, check_extension: bool = True) -> str:
    """
    Joins a base dir with a path string and runs validation.
    """
    # Remove leading slashes so os.path.join doesn't reset to root
    clean_path = path.lstrip("/\\")
    joined = os.path.join(base, clean_path)
    return validate_path(joined, check_extension=check_extension)


def check_file_size(path: str) -> None:
    """
    Raises an error if the file exceeds the maximum allowed size.
    """
    if os.path.exists(path):
        size = os.path.getsize(path)
        if size > MAX_FILE_SIZE:
            raise ValueError(f"File exceeds maximum allowed size of 1MB (Size: {size / 1024 / 1024:.2f}MB).")


# ── Tool Implementations ──────────────────────────────────────

def read_file(path: str) -> str:
    """Read contents of a file securely."""
    try:
        safe_path = safe_join(BASE_DIR, path)
        if not os.path.exists(safe_path):
            return f"I'm sorry, sir. The file '{path}' does not exist."
        if not os.path.isfile(safe_path):
            return f"I'm sorry, sir. '{path}' is a directory, not a file."
            
        check_file_size(safe_path)
        
        with open(safe_path, "r", encoding="utf-8") as f:
            content = f.read(MAX_READ_CHARS + 1)
            if len(content) > MAX_READ_CHARS:
                content = content[:MAX_READ_CHARS] + "\n...[CONTENT TRUNCATED FOR LENGTH]..."
            
        return f"File content for '{path}':\n\n{content}"
    except Exception as e:
        return f"I encountered an error reading the file, sir: {str(e)}"


def write_file(path: str, content: str) -> str:
    """Write or overwrite a file securely."""
    try:
        safe_path = safe_join(BASE_DIR, path)
        
        # Ensure parent directory exists
        parent_dir = os.path.dirname(safe_path)
        os.makedirs(parent_dir, exist_ok=True)
        
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        return f"Certainly, sir. I have successfully written to '{path}'."
    except Exception as e:
        return f"I apologize, sir. I couldn't write the file. Error: {str(e)}"


def append_file(path: str, content: str) -> str:
    """Append content to an existing file securely."""
    try:
        safe_path = safe_join(BASE_DIR, path)
        if not os.path.exists(safe_path):
            return f"I'm sorry, sir. The file '{path}' does not exist. Please create it first."
            
        check_file_size(safe_path)
        
        with open(safe_path, "a", encoding="utf-8") as f:
            # Ensure we append on a new line if not already ending in one, though we keep it simple for now
            f.write(content)
            
        return f"Done, sir. I have appended the text to '{path}'."
    except Exception as e:
        return f"I encountered an error appending to the file, sir: {str(e)}"


def list_directory(path: str = "") -> str:
    """List contents of a directory."""
    try:
        # Don't strictly check extension for directory paths
        safe_path = safe_join(BASE_DIR, path, check_extension=False)
        
        if not os.path.exists(safe_path):
            return f"I'm sorry, sir. The directory '{path}' does not exist."
        if not os.path.isdir(safe_path):
            return f"I'm sorry, sir. '{path}' is a file, not a directory."
            
        items = os.listdir(safe_path)
        if not items:
            return f"The directory '{path or 'workspace'}' is currently empty."
            
        dirs = sorted([d for d in items if os.path.isdir(os.path.join(safe_path, d))])
        files = sorted([f for f in items if os.path.isfile(os.path.join(safe_path, f))])
        
        output = [f"Contents of '{path or 'workspace'}/':"]
        for d in dirs:
            output.append(f" 📁 {d}/")
        for f in files:
            output.append(f" 📄 {f}")
            
        return "\n".join(output)
    except Exception as e:
        return f"I couldn't list the directory contents, sir: {str(e)}"


def search_files(query: str) -> str:
    """Search for files by filename within the workspace."""
    try:
        matched_paths = []
        for root, dirs, files in os.walk(BASE_DIR):
            for file in files:
                if query.lower() in file.lower():
                    # Get relative path for clean display
                    rel_path = os.path.relpath(os.path.join(root, file), BASE_DIR)
                    matched_paths.append(rel_path)
                    
        if not matched_paths:
            return f"I searched the workspace, sir, but could not find any files matching '{query}'."
            
        output = [f"I found the following files matching '{query}':"]
        for match in matched_paths[:20]:  # Limit output to 20 results
            output.append(f" - {match}")
            
        if len(matched_paths) > 20:
            output.append(f"... and {len(matched_paths) - 20} more.")
            
        return "\n".join(output)
    except Exception as e:
        return f"An error occurred while searching for files, sir: {str(e)}"


def search_in_files(query: str) -> str:
    """Search for content inside files within the workspace."""
    try:
        results = []
        for root, dirs, files in os.walk(BASE_DIR):
            for file in files:
                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, BASE_DIR)
                
                # Check extension and size before opening
                _, ext = os.path.splitext(path)
                if ext.lower() not in ALLOWED_EXTENSIONS:
                    continue
                    
                if os.path.getsize(path) > MAX_FILE_SIZE:
                    continue
                    
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        for i, line in enumerate(lines):
                            if query.lower() in line.lower():
                                results.append(f"{rel_path} (line {i+1}): {line.strip()[:100]}")
                                if len(results) >= 20:  # Cap results for latency and context window
                                    break
                except UnicodeDecodeError:
                    pass # Ignore binary or incorrectly encoded files
                        
                if len(results) >= 20:
                    break
        
        if not results:
            return f"I scanned the workspace, sir, but found no text matching '{query}'."
            
        output = [f"Here are the occurrences of '{query}':"]
        output.extend(results)
        if len(results) == 20:
            output.append("... [results truncated]")
            
        return "\n".join(output)
    except Exception as e:
        return f"I encountered an error searching inside files, sir: {str(e)}"
