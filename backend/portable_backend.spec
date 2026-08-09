# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile definition for the local portable backend."""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("sqlalchemy")
    + collect_submodules("jieba")
    + collect_submodules("snownlp")
)
datas = [("stopwords.txt", ".")]
datas += collect_data_files("jieba")
datas += collect_data_files("snownlp")

a = Analysis(
    ["desktop_entry.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
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
    name="BiliOpinionBackend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
