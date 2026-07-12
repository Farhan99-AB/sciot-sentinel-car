# camera_capture.py — v3
# ── Change this one line to switch camera source ─────────────
CAMERA_SOURCE = "ipcam"   # options: "ipcam" | "usb" | "picamera2" | "libcamera"
IPCAM_SNAPSHOT_URL = "http://192.168.1.97:9090/shot.jpg"  # IP Webcam app URL
# ─────────────────────────────────────────────────────────────

import os
import time
from datetime import datetime
from pathlib import Path

PHOTO_DIR = Path("/home/sciot/zwave_ui/evidence")
PHOTO_DIR.mkdir(parents=True, exist_ok=True)


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


def _try_opencv(filepath: str) -> bool:
    """USB webcam via OpenCV — device index 0 (first connected USB cam)."""
    try:
        import cv2
        print("[Camera] Trying USB webcam (OpenCV /dev/video0)")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("[Camera] No USB webcam found at index 0")
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        time.sleep(0.8)   # let auto-exposure settle
        ret, frame = cap.read()
        cap.release()
        if ret:
            cv2.imwrite(filepath, frame)
            return True
        return False
    except Exception as e:
        print(f"[Camera] OpenCV failed: {e}")
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