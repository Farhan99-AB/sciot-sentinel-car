# camera_capture.py — v3
# ── Change this one line to switch camera source ─────────────
CAMERA_SOURCE = "usb"   # options: "ipcam" | "usb" | "picamera2" | "libcamera"
IPCAM_SNAPSHOT_URL = "http://192.168.1.97:9090/shot.jpg"  # IP Webcam app URL
# ─────────────────────────────────────────────────────────────

import os
import time
from datetime import datetime
from pathlib import Path

PHOTO_DIR = Path("/home/sciot/zwave_ui/evidence")
PHOTO_DIR.mkdir(parents=True, exist_ok=True)


import atexit

@atexit.register
def _release_usb_cam():
    global _usb_cam
    if _usb_cam is not None:
        try:
            _usb_cam.release()
        except Exception:
            pass
        _usb_cam = None


def capture_photo(reason: str = "event") -> str | None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"{timestamp}_{reason}.jpg"
    filepath  = str(PHOTO_DIR / filename)
    print(f"[Camera] Capturing → {filename} (source: {CAMERA_SOURCE})")

    dispatch = {
        "ipcam":     _try_ipcam,
        "usb":       _try_opencv,
        "picamera2": _try_picamera2,
        "libcamera": _try_libcamera,
    }

    primary = dispatch.get(CAMERA_SOURCE)
    if primary and primary(filepath):
        print(f"[Camera] Saved: {filepath}")
        return filepath

    # Fallback chain — try everything else in order
    fallback_order = [_try_ipcam, _try_opencv, _try_picamera2, _try_libcamera]
    for method in fallback_order:
        if method == primary:
            continue   # already tried this one
        if method(filepath):
            print(f"[Camera] Saved via fallback {method.__name__}: {filepath}")
            return filepath

    print("[Camera] All capture methods failed")
    return None


def _try_ipcam(filepath: str) -> bool:
    """HTTP snapshot from IP Webcam app (Android) or any MJPEG camera URL."""
    try:
        import urllib.request
        import shutil
        print(f"[Camera] Trying IP cam: {IPCAM_SNAPSHOT_URL}")
        req = urllib.request.Request(
            IPCAM_SNAPSHOT_URL,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            with open(filepath, "wb") as f:
                shutil.copyfileobj(resp, f)
        # Verify file isn't empty
        if os.path.getsize(filepath) > 1000:
            return True
        print("[Camera] IPCam returned empty/tiny file")
        return False
    except Exception as e:
        print(f"[Camera] IPCam failed: {e}")
        return False


USB_CAM_INDEX  = 0       # /dev/video0
USB_CAM_WIDTH  = 640
USB_CAM_HEIGHT = 480
KEEP_CAM_WARM  = False    # hold the device open between captures for fast repeat shots
_usb_cam = None          # cached VideoCapture when KEEP_CAM_WARM is on


def _open_usb_cam():
    """Open /dev/video0 with the fast V4L2 backend + MJPG, buffer minimised."""
    import cv2
    cap = cv2.VideoCapture(USB_CAM_INDEX, cv2.CAP_V4L2)  # V4L2 > GStreamer for USB cams
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))  # compressed = faster
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  USB_CAM_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, USB_CAM_HEIGHT)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # don't hand us a stale buffered frame
    return cap


def _try_opencv(filepath: str) -> bool:
    """USB webcam via OpenCV — device index 0 (first connected USB cam)."""
    global _usb_cam
    try:
        import cv2
        print("[Camera] Trying USB webcam (OpenCV V4L2 /dev/video0)")

        cap = _usb_cam if (KEEP_CAM_WARM and _usb_cam is not None) else _open_usb_cam()
        if cap is None or not cap.isOpened():
            print("[Camera] No USB webcam found at index 0")
            return False

        warm = KEEP_CAM_WARM and _usb_cam is not None
        # Flush a couple of frames so auto-exposure/white-balance has settled.
        # A warm handle only needs a token flush; a freshly opened one needs a few.
        for _ in range(1 if warm else 4):
            cap.read()

        ret, frame = cap.read()

        if KEEP_CAM_WARM:
            _usb_cam = cap            # keep it open for the next shot
        else:
            cap.release()

        if ret and frame is not None:
            cv2.imwrite(filepath, frame)
            return True
        return False
    except Exception as e:
        print(f"[Camera] OpenCV failed: {e}")
        # A cached handle may have gone bad (unplugged) — drop it so we reopen next time.
        if _usb_cam is not None:
            try:
                _usb_cam.release()
            except Exception:
                pass
            _usb_cam = None
        return False


def _try_picamera2(filepath: str) -> bool:
    """Pi Camera Module via picamera2 library."""
    try:
        from picamera2 import Picamera2
        print("[Camera] Trying Pi Camera Module (picamera2)")
        cam = Picamera2()
        cam.configure(cam.create_still_configuration(
            main={"size": (1280, 720)}
        ))
        cam.start()
        time.sleep(1.5)
        cam.capture_file(filepath)
        cam.stop()
        cam.close()
        return True
    except Exception as e:
        print(f"[Camera] picamera2 failed: {e}")
        return False


def _try_libcamera(filepath: str) -> bool:
    """libcamera-still CLI — last resort."""
    try:
        import subprocess
        print("[Camera] Trying libcamera-still")
        result = subprocess.run(
            ["libcamera-still", "-o", filepath,
             "--timeout", "2000", "--nopreview"],
            capture_output=True, timeout=10
        )
        return result.returncode == 0 and os.path.exists(filepath)
    except Exception as e:
        print(f"[Camera] libcamera-still failed: {e}")
        return False


# ── Quick test ────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Testing camera source: {CAMERA_SOURCE}")
    result = capture_photo(reason="test")
    if result:
        print(f"\nSuccess: {result}")
        print(f"File size: {os.path.getsize(result)} bytes")
    else:
        print("\nFailed — check CAMERA_SOURCE and connection")