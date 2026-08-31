# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile definition for the internal stdio MCP component."""

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules


# Keep the stdio transport's Windows-specific imports explicit.  ``mcp[cli]``
# is deliberately not needed by this product component: Inspector remains an
# external development/acceptance tool.
hiddenimports = (
    collect_submodules("mcp.os.win32")
    + [
        "mcp.server.stdio",
        "mcp.server.context",
        "mcp.server.mcpserver.server",
        "mcp.server.mcpserver.exceptions",
        "mcp.os.win32.utilities",
        "mcp_types",
        "win32api",
        "win32con",
        "win32job",
        "pywintypes",
        "agent_mcp.server",
        "agent_mcp.contracts",
        "agent_mcp.read_only_service",
        "services.comment_quality",
        "services.region",
    ]
)
binaries = collect_dynamic_libs("win32")

a = Analysis(
    ["agent_mcp_entry.py"],
    pathex=["."],
    binaries=binaries,
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["mcp.cli", "pytest", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    exclude_binaries=False,
    name="BiliOpinionAgentMcp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
