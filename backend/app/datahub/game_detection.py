"""Read-only FM27 process detection for the data hub status panel (V3.3.0).

Only process metadata and the executable's version resource are read; the game memory is never touched here.
Detection failure is reported as ``detected=False`` (unknown), never as "not running", so the UI does not tell
the user to start a game that might actually be running.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

GAME_EXECUTABLE = "fm.exe"
_CACHE_TTL_SECONDS = 10.0
_cache: tuple[float, "GameDetection"] | None = None


@dataclass(frozen=True)
class GameDetection:
    """Result of one process lookup."""

    running: bool
    detected: bool
    pid: int | None = None
    exe_path: str | None = None
    version: str | None = None
    message: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            "running": self.running,
            "detected": self.detected,
            "pid": self.pid,
            "version": self.version,
            "exe_path": self.exe_path,
            "message": self.message,
        }


def _file_version(path: str) -> str | None:
    """Read the executable's fixed file version, e.g. ``27.1.0.0``; ``None`` when unreadable."""
    try:
        import ctypes
        from ctypes import wintypes

        version_dll = ctypes.WinDLL("version")
        version_dll.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        version_dll.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version_dll.GetFileVersionInfoW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        ]
        version_dll.GetFileVersionInfoW.restype = wintypes.BOOL
        version_dll.VerQueryValueW.argtypes = [
            ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT),
        ]
        version_dll.VerQueryValueW.restype = wintypes.BOOL

        size = version_dll.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not version_dll.GetFileVersionInfoW(path, 0, size, buffer):
            return None
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version_dll.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return None

        class _FixedFileInfo(ctypes.Structure):
            _fields_ = [
                ("dwSignature", wintypes.DWORD),
                ("dwStrucVersion", wintypes.DWORD),
                ("dwFileVersionMS", wintypes.DWORD),
                ("dwFileVersionLS", wintypes.DWORD),
                ("dwProductVersionMS", wintypes.DWORD),
                ("dwProductVersionLS", wintypes.DWORD),
                ("dwFileFlagsMask", wintypes.DWORD),
                ("dwFileFlags", wintypes.DWORD),
                ("dwFileOS", wintypes.DWORD),
                ("dwFileType", wintypes.DWORD),
                ("dwFileSubtype", wintypes.DWORD),
                ("dwFileDateMS", wintypes.DWORD),
                ("dwFileDateLS", wintypes.DWORD),
            ]

        info = ctypes.cast(pointer, ctypes.POINTER(_FixedFileInfo)).contents
        ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:  # noqa: BLE001 - 版本读取失败只影响展示，不影响同步
        return None


def _windows_process_path(pid: int) -> str | None:
    """Full image path of one process; requires only PROCESS_QUERY_LIMITED_INFORMATION."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buffer))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value or None
            return None
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        return None


def _enumerate_processes() -> list[tuple[int, str]]:
    """All ``(pid, exe file name)`` pairs; raises when the platform cannot enumerate them."""
    if sys.platform != "win32":
        raise OSError("进程检测仅支持 Windows")
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    class _ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snapshot == wintypes.HANDLE(-1).value:
        raise OSError("无法枚举进程")
    entry = _ProcessEntry32W()
    entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
    processes: list[tuple[int, str]] = []
    try:
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return processes
        while True:
            processes.append((int(entry.th32ProcessID), entry.szExeFile))
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return processes


def detect_game(*, force: bool = False) -> GameDetection:
    """Locate a running ``fm.exe``; cached briefly because the status endpoint is polled by the UI."""
    global _cache
    now = time.monotonic()
    if not force and _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    try:
        processes = _enumerate_processes()
    except Exception as exc:  # noqa: BLE001 - 未知即未知，不能谎报“未运行”
        result = GameDetection(running=False, detected=False, message=f"无法检测游戏进程：{exc}")
        _cache = (now, result)
        return result
    matches = [(pid, name) for pid, name in processes if name.lower() == GAME_EXECUTABLE]
    if not matches:
        result = GameDetection(running=False, detected=True, message="未检测到 Football Manager 27")
    else:
        pid = matches[0][0]
        path = _windows_process_path(pid)
        result = GameDetection(
            running=True,
            detected=True,
            pid=pid,
            exe_path=path,
            version=_file_version(path) if path else None,
        )
    _cache = (now, result)
    return result


def clear_cache() -> None:
    """Drop the cached detection (tests and explicit refresh)."""
    global _cache
    _cache = None
