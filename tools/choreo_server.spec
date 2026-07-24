# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for A1Z 编舞器
# 在 tools/ 目录下运行：pyinstaller choreo_server.spec

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs

HERE = Path(SPECPATH)          # tools/
ROOT = HERE.parent             # sport/
MESH_SRC = ROOT / 'A1Z_Flange' / 'meshes'

# Collect MuJoCo DLLs + glfw DLLs (both needed for GLFW/WGL rendering on Windows)
# collect_dynamic_libs('mujoco') 只收集 mujoco 的原生库
# collect_dynamic_libs('glfw')   收集 glfw3.dll（Windows 渲染必须）
mujoco_bins = collect_dynamic_libs('mujoco')
try:
    glfw_bins = collect_dynamic_libs('glfw')
except Exception:
    glfw_bins = []

all_bins = mujoco_bins + glfw_bins

a = Analysis(
    [str(HERE / 'choreo_server.py')],
    pathex=[str(HERE)],
    binaries=all_bins,
    datas=[
        # 前端页面
        (str(HERE / 'static'),       'static'),
        # STL 网格文件
        (str(MESH_SRC),              'meshes'),
    ],
    hiddenimports=[
        # uvicorn 动态加载模块
        'uvicorn.logging',
        'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan', 'uvicorn.lifespan.on',
        # FastAPI / Starlette
        'fastapi', 'starlette', 'starlette.routing', 'starlette.websockets',
        'starlette.responses', 'starlette.staticfiles',
        # 网络库
        'h11', 'websockets', 'websockets.legacy', 'websockets.legacy.server',
        'anyio', 'anyio._backends._asyncio', 'anyio.abc',
        # GL / 渲染
        'glfw',
        'mujoco.glfw',
        'mujoco.rendering.classic.gl_context',
        'mujoco.rendering.classic.renderer',
        # OpenGL platform (EGL on Linux)
        'OpenGL', 'OpenGL.platform', 'OpenGL.platform.egl',
        'OpenGL.platform.glx', 'OpenGL.platform.osmesa',
        'OpenGL.GL', 'OpenGL.EGL',
        # 其他
        'PIL._tkinter_finder',
        'numpy',
        'mujoco',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'PyQt5', 'PySide6'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='A1Z',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,               # 保留控制台窗口方便排查；发布改 False
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='A1Z',
)
