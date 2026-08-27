# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.building.api import MERGE
from PyInstaller.utils.hooks import collect_submodules


hiddenimports = (
    collect_submodules("app")
    + collect_submodules("jose")
    + [
    "passlib.handlers.bcrypt",
    "passlib.handlers.pbkdf2",
    "passlib.handlers.sha2_crypt",
    "fastapi",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "sqlalchemy",
    "pymysql",
    "passlib.handlers.bcrypt",
    "pydantic_settings",
]
)


a = Analysis(
    ["service_main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "printer_agent", "passlib.tests"],
    noarchive=False,
    optimize=0,
)
schema_migrations = Analysis(
    ["schema_migrations_main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "printer_agent", "passlib.tests"],
    noarchive=False,
    optimize=0,
)
MERGE((a, "EstacionamientoCentralAPI", "."), (schema_migrations, "EstacionamientoCentralSchemaMigrations", "."))

pyz = PYZ(a.pure)
schema_migrations_pyz = PYZ(schema_migrations.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EstacionamientoCentralAPI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
schema_migrations_exe = EXE(
    schema_migrations_pyz,
    schema_migrations.dependencies,
    schema_migrations.scripts,
    [],
    exclude_binaries=True,
    name="EstacionamientoCentralSchemaMigrations",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    schema_migrations_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EstacionamientoCentralAPI",
)
