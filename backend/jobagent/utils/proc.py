"""Small process helpers that behave the same on macOS, Linux and Windows."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

WINDOWS = sys.platform == "win32"


def pid_alive(pid: int | None) -> bool:
    """True if a process with this id is running. Never signals it: on Windows `os.kill(pid, 0)` would end the process,
    so there it is looked up with OpenProcess instead."""
    if not pid or pid <= 0:
        return False
    if WINDOWS:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        query_limited, still_active = 0x1000, 259
        handle = kernel32.OpenProcess(query_limited, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5           # access denied: it exists, it just isn't ours
        try:
            code = wintypes.DWORD()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                                        # exists, owned by someone else
    except OSError:
        return False
    return True


def detached() -> dict[str, Any]:
    """Popen arguments that let a child (a sign-in window) outlive the request that started it."""
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
    return {"start_new_session": True}
