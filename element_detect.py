"""Snipaste-style element detection under the cursor.

Strategy: a fast top-level HWND walk finds the window under the point
(skipping our own process, click-through overlays, cloaked and hidden
windows), then UI Automation walks that window's element tree down to the
deepest element containing the point — this is what sees browser page
containers and other HWND-less controls. Our own overlay never interferes
because detection never hit-tests it.

Detection involves cross-process COM and can be slow on busy apps, so
DetectThread runs it off the GUI thread and only ever works on the latest
requested point.

COM vtable indices follow UIAutomationClient.idl and were verified on a live
Windows 11 desktop (ElementFromPoint=7, CurrentProcessId=20,
CurrentBoundingRectangle=43 confirmed empirically).
"""
import ctypes
import os
import sys
import threading
import uuid
from ctypes import wintypes

from PySide6.QtCore import QThread, Signal


class RECT(ctypes.Structure):
    _fields_ = [('left',wintypes.LONG),('top',wintypes.LONG),
                ('right',wintypes.LONG),('bottom',wintypes.LONG)]


class GUID(ctypes.Structure):
    _fields_ = [('Data1',wintypes.DWORD),('Data2',wintypes.WORD),
                ('Data3',wintypes.WORD),('Data4',ctypes.c_ubyte*8)]


def _guid(text):
    g = GUID()
    ctypes.memmove(ctypes.byref(g),uuid.UUID(text).bytes_le,16)
    return g


def _rect_tuple(rect):
    return (rect.left,rect.top,rect.right,rect.bottom)


def _area(rect):
    return max(0,rect[2]-rect[0])*max(0,rect[3]-rect[1])


def _contains(rect,x,y):
    return rect[0] <= x < rect[2] and rect[1] <= y < rect[3]


_GW_HWNDNEXT = 2
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x20  # click-through overlays: handwriting canvas, GPU OSDs
_DWMWA_CLOAKED = 14


def _configure_user32(user32):
    for name in ('GetTopWindow','GetWindow'):
        getattr(user32,name).restype = ctypes.c_void_p
    user32.GetWindow.argtypes = [ctypes.c_void_p,ctypes.c_uint]
    user32.GetTopWindow.argtypes = [ctypes.c_void_p]
    user32.GetWindowRect.argtypes = [ctypes.c_void_p,ctypes.POINTER(RECT)]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsIconic.argtypes = [ctypes.c_void_p]
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowLongW.argtypes = [ctypes.c_void_p,ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG


def top_window_at(x,y,own_pid):
    """Top-level window under the point as (hwnd, rect); skips everything that
    is not a real clickable window. Never blocks: pure Z-order walk, no
    child-window hit testing (which can send messages into busy apps)."""
    if sys.platform != 'win32':
        return None
    user32 = ctypes.windll.user32
    _configure_user32(user32)
    dwm = ctypes.windll.dwmapi
    hwnd = user32.GetTopWindow(None)
    while hwnd:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        cloaked = wintypes.DWORD()
        dwm.DwmGetWindowAttribute(ctypes.c_void_p(hwnd),_DWMWA_CLOAKED,
                                  ctypes.byref(cloaked),ctypes.sizeof(cloaked))
        click_through = bool(user32.GetWindowLongW(hwnd,_GWL_EXSTYLE) & _WS_EX_TRANSPARENT)
        rect = RECT()
        if (pid.value != own_pid and not cloaked.value and not click_through
                and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd)
                and user32.GetWindowRect(hwnd,ctypes.byref(rect))
                and rect.left <= x < rect.right and rect.top <= y < rect.bottom):
            return hwnd,_rect_tuple(rect)
        hwnd = user32.GetWindow(hwnd,_GW_HWNDNEXT)
    return None


_CLSCTX_ALL = 23
_CLSID_CUIAUTOMATION = '{FF48DBA4-60EF-4201-AA87-54103EEF594E}'
_IID_IUIAUTOMATION = '{30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}'
_TREE_SCOPE_CHILDREN = 2
# IUnknown: QueryInterface=0, AddRef=1, Release=2
_RELEASE = 2
# IUIAutomation vtable indices (see module docstring)
_ELEMENT_FROM_HANDLE = 6
_GET_RAW_VIEW_CONDITION = 17
# IUIAutomationElement vtable indices
_FIND_ALL = 6
_GET_PROCESS_ID = 20
_GET_BOUNDING_RECT = 43
# IUIAutomationElementArray vtable indices
_GET_LENGTH = 3
_GET_ELEMENT = 4

_MAX_DEPTH = 24
_MAX_CHILDREN = 800


def _method(ptr,index,proto):
    vtable = ctypes.cast(ptr,ctypes.POINTER(ctypes.c_void_p)).contents
    entry = ctypes.cast(vtable,ctypes.POINTER(ctypes.c_void_p))[index]
    return proto(entry)


def _release(ptr):
    if ptr:
        _method(ptr,_RELEASE,ctypes.WINFUNCTYPE(ctypes.c_ulong,ctypes.c_void_p))(ptr)


class _Uia:
    """Minimal raw-COM UI Automation client; no third-party dependency."""

    _HRES = wintypes.LONG

    def __init__(self):
        ole32 = ctypes.windll.ole32
        # UIA cross-process calls from a worker thread must be MTA; a fresh STA
        # without a message pump blocks for seconds. In a GUI thread Qt has
        # already made us STA and this returns RPC_E_CHANGED_MODE, which is fine.
        ole32.CoInitializeEx(None,0)
        self._ptr = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID_CUIAUTOMATION)),None,_CLSCTX_ALL,
                                    ctypes.byref(_guid(_IID_IUIAUTOMATION)),ctypes.byref(self._ptr))
        if hr != 0 or not self._ptr:
            raise OSError(f'UI Automation 初始化失败：0x{hr & 0xFFFFFFFF:08X}')
        self._raw_condition = ctypes.c_void_p()
        hr = _method(self._ptr,_GET_RAW_VIEW_CONDITION,
                     ctypes.WINFUNCTYPE(self._HRES,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p))
                     )(self._ptr,ctypes.byref(self._raw_condition))
        if hr != 0 or not self._raw_condition:
            self.close()
            raise OSError('无法获取 UI Automation 视图条件。')

    def _element_rect(self,elem):
        rect = RECT()
        hr = _method(elem,_GET_BOUNDING_RECT,
                     ctypes.WINFUNCTYPE(self._HRES,ctypes.c_void_p,ctypes.POINTER(RECT))
                     )(elem,ctypes.byref(rect))
        if hr != 0:
            return None
        result = _rect_tuple(rect)
        if result[2] <= result[0] or result[3] <= result[1]:
            return None
        return result

    def deepest_at(self,hwnd,x,y,own_pid):
        """Deepest element containing (x,y) inside the window's UIA tree."""
        root = ctypes.c_void_p()
        hr = _method(self._ptr,_ELEMENT_FROM_HANDLE,
                     ctypes.WINFUNCTYPE(self._HRES,ctypes.c_void_p,ctypes.c_void_p,
                                        ctypes.POINTER(ctypes.c_void_p))
                     )(self._ptr,ctypes.c_void_p(hwnd),ctypes.byref(root))
        if hr != 0 or not root:
            return None
        elem,best = root,None
        try:
            pid = wintypes.DWORD()
            _method(elem,_GET_PROCESS_ID,
                    ctypes.WINFUNCTYPE(self._HRES,ctypes.c_void_p,ctypes.POINTER(wintypes.DWORD))
                    )(elem,ctypes.byref(pid))
            if pid.value == own_pid:
                return None
            best = self._element_rect(elem)
            if best is None:
                return None
            for _ in range(_MAX_DEPTH):
                array = ctypes.c_void_p()
                hr = _method(elem,_FIND_ALL,
                             ctypes.WINFUNCTYPE(self._HRES,ctypes.c_void_p,ctypes.c_int,
                                                ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p))
                             )(elem,_TREE_SCOPE_CHILDREN,self._raw_condition,ctypes.byref(array))
                if hr != 0 or not array:
                    break
                child,child_rect = None,None
                try:
                    count = ctypes.c_int()
                    _method(array,_GET_LENGTH,
                            ctypes.WINFUNCTYPE(self._HRES,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int))
                            )(array,ctypes.byref(count))
                    for i in range(min(count.value,_MAX_CHILDREN)):
                        candidate = ctypes.c_void_p()
                        hr = _method(array,_GET_ELEMENT,
                                     ctypes.WINFUNCTYPE(self._HRES,ctypes.c_void_p,ctypes.c_int,
                                                        ctypes.POINTER(ctypes.c_void_p))
                                     )(array,i,ctypes.byref(candidate))
                        if hr != 0 or not candidate:
                            continue
                        rect = self._element_rect(candidate)
                        if rect and _contains(rect,x,y) and _area(rect) < _area(best):
                            child,child_rect = candidate,rect
                            break
                        _release(candidate)
                finally:
                    _release(array)
                if child is None:
                    break
                _release(elem)
                elem,best = child,child_rect
            return best
        finally:
            _release(elem)

    def close(self):
        _release(self._raw_condition)
        self._raw_condition = None
        _release(self._ptr)
        self._ptr = None


class ElementDetector:
    """GUI-thread affine use is safe; intended to live on DetectThread."""

    def __init__(self):
        self.own_pid = os.getpid()
        self._uia = None
        self._uia_broken = sys.platform != 'win32'

    def _ensure_uia(self):
        if self._uia is None and not self._uia_broken:
            try:
                self._uia = _Uia()
            except Exception:
                self._uia_broken = True
        return self._uia

    def rect_at(self,x,y):
        """Physical (left,top,right,bottom) under the point, or None."""
        if sys.platform != 'win32':
            return None
        top = top_window_at(x,y,self.own_pid)
        if top is None:
            return None
        hwnd,hwnd_rect = top
        uia = self._ensure_uia()
        if uia is not None:
            try:
                rect = uia.deepest_at(hwnd,x,y,self.own_pid)
                if rect is not None:
                    return rect
            except Exception:
                self._uia_broken = True
                self.close()
        return hwnd_rect

    def close(self):
        if self._uia is not None:
            try:
                self._uia.close()
            except Exception:
                pass
            self._uia = None


class DetectThread(QThread):
    """Runs ElementDetector off the GUI thread; stale points are dropped."""

    detected = Signal(object, object)  # requester, rect tuple or None

    def __init__(self, parent=None, detector_factory=None):
        super().__init__(parent)
        self._factory = detector_factory or ElementDetector
        self._lock = threading.Lock()
        self._pending = None
        self._wake = threading.Event()
        self._quit = False

    def request(self, requester, x, y):
        with self._lock:
            self._pending = (requester, x, y)
        self._wake.set()

    def run(self):
        detector = self._factory()
        try:
            while True:
                self._wake.wait()
                self._wake.clear()
                if self._quit:
                    break
                with self._lock:
                    job = self._pending
                if job is None:
                    continue
                requester, x, y = job
                try:
                    rect = detector.rect_at(x, y)
                except Exception:
                    rect = None
                with self._lock:
                    stale = self._pending is not job
                if not stale:
                    self.detected.emit(requester, rect)
        finally:
            try:
                detector.close()
            except Exception:
                pass

    def stop(self):
        self._quit = True
        self._wake.set()
        self.wait(3000)
