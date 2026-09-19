"""
Photograph one Tk window by its handle.

`PrintWindow` asks Windows to render that window's own pixels, so whatever is
on top of it - including a writer's real NovelForge window, or a screen
recorder - cannot end up in the picture. A screen-region grab (ImageGrab) does
exactly that, and once photographed the wrong window.

Two limits worth knowing: a window must be fully on the screen to be captured
whole (off-screen parts come out black - on a 1366x768 laptop, a 1382x788
window shows black bands that are not a bug in the app), and popup *menus* are
separate native windows; see `menu_popups()` in `shots.py`.
"""

import ctypes
from ctypes import wintypes

from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
PW_RENDERFULLCONTENT = 2


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def capture_hwnd(hwnd: int, path: str, client_only: bool = False):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(info)
    info.biWidth, info.biHeight = w, -h
    info.biPlanes, info.biBitCount = 1, 32
    buffer = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buffer, ctypes.byref(info), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    image = Image.frombuffer("RGBA", (w, h), buffer, "raw", "BGRA", 0, 1).convert("RGB")
    if client_only:
        # Just the app's own area, without Windows' title bar and frame - what
        # the website wants, since the page draws its own window chrome.
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(origin))
        inner = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(inner))
        left, top = origin.x - rect.left, origin.y - rect.top
        image = image.crop((left, top, left + inner.right, top + inner.bottom))
    image.save(path)
    return image.size


def capture(window, path: str, client_only: bool = False):
    """Save a picture of a Tk window (main window or Toplevel) to `path`."""
    window.update()
    hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
    return capture_hwnd(hwnd, path, client_only)
