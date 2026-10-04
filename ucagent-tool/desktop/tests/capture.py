"""Capture only the tested native Tk window using Windows APIs and standard-library PNG encoding."""

import ctypes
from ctypes import wintypes
import struct
import zlib


def capture_window(root, destination):
    """Capture this application window, not the desktop or unrelated application content."""
    root.update_idletasks()
    user = ctypes.WinDLL("user32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    user.GetWindowDC.argtypes = [wintypes.HWND]
    user.GetWindowDC.restype = wintypes.HDC
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wintypes.HANDLE
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HANDLE, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    window = user.GetParent(root.winfo_id())
    rect = wintypes.RECT()
    if not user.GetWindowRect(window, ctypes.byref(rect)):
        raise OSError("Cannot resolve the tested Tk window bounds")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    source = user.GetWindowDC(window)
    memory = gdi.CreateCompatibleDC(source)
    bitmap = gdi.CreateCompatibleBitmap(source, width, height)
    original = gdi.SelectObject(memory, bitmap)
    try:
        if not user.PrintWindow(window, memory, 2):
            raise OSError("PrintWindow did not capture the Tk window")
        info = ctypes.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0))
        pixels = ctypes.create_string_buffer(width * height * 4)
        gdi.SelectObject(memory, original)
        if not gdi.GetDIBits(memory, bitmap, 0, height, pixels, info, 0):
            raise OSError("Cannot read the captured Tk bitmap")
        data = pixels.raw
        scanlines = []
        for row in range(height):
            bgra = data[row * width * 4:(row + 1) * width * 4]
            rgb = bytearray(width * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
            scanlines.append(b"\0" + rgb)
        output = b"\x89PNG\r\n\x1a\n"
        for kind, value in ((b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)), (b"IDAT", zlib.compress(b"".join(scanlines))), (b"IEND", b"")):
            output += struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)
        destination.write_bytes(output)
    finally:
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(window, source)
