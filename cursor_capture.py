"""Composite the real Windows cursor over an MSS BGRA frame.

MSS intentionally captures desktop pixels without the system cursor. Drawing the
HCURSOR into a memory DIB preserves custom cursors, their hotspots, and legacy
XOR/mask rendering against the captured background.
"""
import ctypes
import sys
from ctypes import wintypes


DEFAULT_CURSOR_SIZE = 32


class CURSORINFO(ctypes.Structure):
    _fields_ = [('cbSize',wintypes.DWORD),('flags',wintypes.DWORD),
                ('hCursor',wintypes.HANDLE),('ptScreenPos',wintypes.POINT)]


class ICONINFO(ctypes.Structure):
    _fields_ = [('fIcon',wintypes.BOOL),('xHotspot',wintypes.DWORD),
                ('yHotspot',wintypes.DWORD),('hbmMask',wintypes.HBITMAP),
                ('hbmColor',wintypes.HBITMAP)]


class BITMAP(ctypes.Structure):
    _fields_ = [('bmType',wintypes.LONG),('bmWidth',wintypes.LONG),
                ('bmHeight',wintypes.LONG),('bmWidthBytes',wintypes.LONG),
                ('bmPlanes',wintypes.WORD),('bmBitsPixel',wintypes.WORD),
                ('bmBits',wintypes.LPVOID)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize',wintypes.DWORD),('biWidth',wintypes.LONG),
                ('biHeight',wintypes.LONG),('biPlanes',wintypes.WORD),
                ('biBitCount',wintypes.WORD),('biCompression',wintypes.DWORD),
                ('biSizeImage',wintypes.DWORD),('biXPelsPerMeter',wintypes.LONG),
                ('biYPelsPerMeter',wintypes.LONG),('biClrUsed',wintypes.DWORD),
                ('biClrImportant',wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader',BITMAPINFOHEADER),('bmiColors',wintypes.DWORD*1)]


def _configure(user32,gdi32):
    user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
    user32.GetCursorInfo.restype = wintypes.BOOL
    user32.GetIconInfo.argtypes = [wintypes.HANDLE,ctypes.POINTER(ICONINFO)]
    user32.GetIconInfo.restype = wintypes.BOOL
    user32.DrawIconEx.argtypes = [wintypes.HDC,ctypes.c_int,ctypes.c_int,
        wintypes.HANDLE,ctypes.c_int,ctypes.c_int,wintypes.UINT,wintypes.HBRUSH,wintypes.UINT]
    user32.DrawIconEx.restype = wintypes.BOOL
    gdi32.GetObjectW.argtypes = [wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID]
    gdi32.GetObjectW.restype = ctypes.c_int
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC,ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,ctypes.POINTER(ctypes.c_void_p),wintypes.HANDLE,wintypes.DWORD]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC,wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]


def _configured_cursor_base_size():
    """Windows accessibility pointer size at 96 DPI (32 is the default)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Control Panel\Cursors') as key:
            value = int(winreg.QueryValueEx(key,'CursorBaseSize')[0])
            return value if 16 <= value <= 256 else DEFAULT_CURSOR_SIZE
    except (OSError,TypeError,ValueError):
        return DEFAULT_CURSOR_SIZE


def _effective_dpi(user32,point):
    """Return the DPI of the monitor currently displaying the cursor."""
    try:
        user32.MonitorFromPoint.argtypes = [wintypes.POINT,wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        monitor = user32.MonitorFromPoint(point,2)
        get_dpi = ctypes.windll.shcore.GetDpiForMonitor
        get_dpi.argtypes = [wintypes.HMONITOR,ctypes.c_int,
                            ctypes.POINTER(wintypes.UINT),ctypes.POINTER(wintypes.UINT)]
        x,y = wintypes.UINT(),wintypes.UINT()
        if monitor and get_dpi(monitor,0,ctypes.byref(x),ctypes.byref(y)) == 0 and x.value:
            return x.value
    except Exception:
        pass
    return 96


def scaled_cursor_geometry(width,height,x_hotspot,y_hotspot,base_size,dpi):
    """Scale the cursor canvas and hotspot to its physical on-screen size."""
    expected = max(1,round(base_size*dpi/96))
    # Some cursor handles already expose an accessibility/DPI-sized bitmap.
    # Never shrink those; only supply the scale missing from a smaller handle.
    draw_width = max(width,expected)
    scale = draw_width/width
    draw_height = max(1,round(height*scale))
    return draw_width,draw_height,round(x_hotspot*scale),round(y_hotspot*scale)


def compose_cursor(bgra,width,height,region):
    """Return immutable BGRA bytes with the visible cursor, or original bytes."""
    if sys.platform != 'win32': return bgra
    if len(bgra) != width*height*4: return bgra
    user32,gdi32 = ctypes.windll.user32,ctypes.windll.gdi32
    _configure(user32,gdi32)
    cursor = CURSORINFO(cbSize=ctypes.sizeof(CURSORINFO))
    if not user32.GetCursorInfo(ctypes.byref(cursor)) or cursor.flags != 1:
        return bgra
    icon = ICONINFO()
    if not user32.GetIconInfo(cursor.hCursor,ctypes.byref(icon)):
        return bgra
    try:
        bitmap = BITMAP()
        source = icon.hbmColor or icon.hbmMask
        if not source or not gdi32.GetObjectW(source,ctypes.sizeof(bitmap),ctypes.byref(bitmap)):
            return bgra
        bitmap_width = bitmap.bmWidth
        bitmap_height = bitmap.bmHeight if icon.hbmColor else bitmap.bmHeight//2
        cursor_width,cursor_height,hotspot_x,hotspot_y = scaled_cursor_geometry(
            bitmap_width,bitmap_height,icon.xHotspot,icon.yHotspot,
            _configured_cursor_base_size(),_effective_dpi(user32,cursor.ptScreenPos))
        x = cursor.ptScreenPos.x-region['left']-hotspot_x
        y = cursor.ptScreenPos.y-region['top']-hotspot_y
        if x >= width or y >= height or x+cursor_width <= 0 or y+cursor_height <= 0:
            return bgra
        dc = gdi32.CreateCompatibleDC(None)
        if not dc: return bgra
        bits = ctypes.c_void_p()
        info = BITMAPINFO(BITMAPINFOHEADER(
            ctypes.sizeof(BITMAPINFOHEADER),width,-height,1,32,0,
            width*height*4,0,0,0,0),(wintypes.DWORD*1)(0))
        dib = gdi32.CreateDIBSection(dc,ctypes.byref(info),0,ctypes.byref(bits),None,0)
        if not dib:
            gdi32.DeleteDC(dc)
            return bgra
        old = gdi32.SelectObject(dc,dib)
        try:
            size = width*height*4
            ctypes.memmove(bits,bgra,size)
            if not user32.DrawIconEx(dc,x,y,cursor.hCursor,cursor_width,cursor_height,0,None,3):
                return bgra
            return ctypes.string_at(bits,size)
        finally:
            gdi32.SelectObject(dc,old)
            gdi32.DeleteObject(dib)
            gdi32.DeleteDC(dc)
    finally:
        if icon.hbmMask: gdi32.DeleteObject(icon.hbmMask)
        if icon.hbmColor: gdi32.DeleteObject(icon.hbmColor)
