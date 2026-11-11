"""Run any registered subsidiary node by ID, so a new node needs a registry entry and a pack, no module file.

    python -m mcp_nodes ceat
"""
from __future__ import annotations

import sys

from mcp_nodes.server import NODE_IDS, serve_node

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in NODE_IDS:
        sys.exit(f"usage: python -m mcp_nodes <node id>  (registered: {', '.join(NODE_IDS)})")
    serve_node(sys.argv[1])
