"""Explicit conversion from screen-local Qt units to MSS physical pixels."""
import ctypes
import os
import sys


def external_foreground_window():
    """Remember the user's foreground app, never one of our own tool windows."""
    if sys.platform != 'win32': return None
    api = ctypes.windll.user32
    api.GetForegroundWindow.restype = ctypes.c_void_p
    hwnd = api.GetForegroundWindow()
    if not hwnd: return None
    pid = ctypes.c_ulong()
    api.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    api.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    return hwnd if pid.value != os.getpid() else None


def restore_foreground_window(hwnd):
    """Best effort: do not move, resize or unminimize the user's target window."""
    if sys.platform != 'win32' or not hwnd: return False
    api = ctypes.windll.user32
    api.IsWindowVisible.argtypes = [ctypes.c_void_p]
    api.IsIconic.argtypes = [ctypes.c_void_p]
    api.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    if not api.IsWindowVisible(hwnd) or api.IsIconic(hwnd): return False
    return bool(api.SetForegroundWindow(hwnd))

def physical_region(rect, logical_size, monitor):
    sx = monitor['width'] / logical_size.width()
    sy = monitor['height'] / logical_size.height()
    left = max(0, round(rect.x()*sx))
    top = max(0, round(rect.y()*sy))
    right = min(monitor['width'], round((rect.x()+rect.width())*sx))
    bottom = min(monitor['height'], round((rect.y()+rect.height())*sy))
    return dict(left=monitor['left']+left, top=monitor['top']+top,
                width=max(1, right-left), height=max(1, bottom-top))

def monitor_for_screen(screen, monitors):
    g = screen.geometry()
    # Windows Qt scales screen sizes, but retains native monitor origins.
    matches = [m for m in monitors if (m['left'],m['top']) == (g.x(),g.y())]
    if len(matches) == 1:
        return matches[0]
    raise RuntimeError(f'无法匹配显示器 {screen.name()}。请重新连接显示器后重试。')

def exclude_from_capture(widget):
    if sys.platform != 'win32' or sys.getwindowsversion().build < 19041:
        return False
    fn = ctypes.windll.user32.SetWindowDisplayAffinity
    fn.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    return bool(fn(int(widget.winId()), 0x11))
