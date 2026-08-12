"""Model Context Protocol exposure for the controlled virtual filesystem."""

from .server import (
    VFS_MCP_TOOL_NAMES,
    create_vfs_mcp_server,
    load_virtual_file_system,
    serve_vfs_mcp_stdio,
)

__all__ = [
    "VFS_MCP_TOOL_NAMES",
    "create_vfs_mcp_server",
    "load_virtual_file_system",
    "serve_vfs_mcp_stdio",
]
