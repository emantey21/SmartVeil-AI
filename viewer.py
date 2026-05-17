import subprocess
import logging
import signal
import sys
from threading import Thread

logger = logging.getLogger(__name__)


def view_single(name: str, url: str, transport: str = "tcp"):
    """View a single RTSP stream using ffplay."""
    cmd = [
        "ffplay",
        "-rtsp_transport", transport,
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-framedrop",
        "-strict", "experimental",
        "-window_title", f"CCTV - {name}",
        "-i", url,
    ]

    logger.info("Opening viewer for %s", name)
    process = subprocess.Popen(cmd)

    def shutdown(sig, frame):
        process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
        process.wait()


def view_grid(channels: list[tuple[str, str]], transport: str = "tcp"):
    """View multiple RTSP streams in a grid using OpenCV."""
    try:
        import cv2
    except ImportError:
        logger.error(
            "OpenCV is required for grid view. Install it with: pip install opencv-python"
        )
        sys.exit(1)

    caps = []
    for name, url in channels:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            logger.warning("Failed to open stream: %s (%s)", name, url)
            continue
        caps.append((name, cap))

    if not caps:
        logger.error("No streams could be opened.")
        return

    import math
    n = len(caps)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)

    win_name = "SmartVeil AI Grid"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)

    logger.info("Viewing %d channels in a %dx%d grid", n, cols, rows)

    try:
        while True:
            tiles = []
            for name, cap in caps:
                ret, frame = cap.read()
                if not ret:
                    frame = _placeholder_frame(name)
                else:
                    h, w = frame.shape[:2]
                    scale = 320 / w
                    new_w, new_h = 320, int(h * scale)
                    frame = cv2.resize(frame, (new_w, new_h))
                    cv2.putText(frame, name, (8, 24),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                tiles.append(frame)

            grid = _assemble_grid(tiles, rows, cols)
            cv2.imshow(win_name, grid)

            key = cv2.waitKey(30) & 0xFF
            if key == 27 or key == ord('q'):
                break
    finally:
        for _, cap in caps:
            cap.release()
        cv2.destroyAllWindows()


def _placeholder_frame(label: str):
    import numpy as np
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.putText(frame, label, (10, 120),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return frame


def _assemble_grid(tiles, rows, cols):
    import cv2
    for _ in range(rows * cols - len(tiles)):
        tiles.append(_placeholder_frame(""))

    rows_list = []
    for r in range(rows):
        row_tiles = tiles[r * cols:(r + 1) * cols]
        rows_list.append(cv2.hconcat(row_tiles))
    return cv2.vconcat(rows_list)
