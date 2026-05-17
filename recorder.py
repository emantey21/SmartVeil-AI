import subprocess
import time
import signal
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class ChannelRecorder:
    def __init__(self, name: str, url: str, base_dir: str,
                 segment_time: int = 600, transport: str = "tcp"):
        self.name = name
        self.url = url
        self.base_dir = Path(base_dir)
        self.segment_time = segment_time
        self.transport = transport
        self.process: subprocess.Popen | None = None

    @property
    def channel_dir(self) -> Path:
        return self.base_dir / self.name / datetime.now().strftime("%Y-%m-%d")

    def start(self):
        self.channel_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.channel_dir / f"{self.name}.log"
        output_pattern = str(
            self.channel_dir / f"{self.name}_%Y-%m-%d_%H-%M-%S.mp4"
        )

        cmd = [
            "ffmpeg",
            "-rtsp_transport", self.transport,
            "-i", self.url,
            "-c:v", "copy",
            "-c:a", "copy",
            "-f", "segment",
            "-segment_time", str(self.segment_time),
            "-reset_timestamps", "1",
            "-strftime", "1",
            output_pattern,
        ]

        with open(log_file, "a") as f:
            self.process = subprocess.Popen(
                cmd, stdout=f, stderr=subprocess.STDOUT,
            )

        logger.info("Started recording %s (PID %d)", self.name, self.process.pid)

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            logger.info("Stopped recording %s", self.name)

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def restart(self):
        self.stop()
        time.sleep(1)
        self.start()


class RecorderManager:
    def __init__(self):
        self.recorders: dict[str, ChannelRecorder] = {}

    def add(self, name: str, url: str, base_dir: str, **kwargs):
        self.recorders[name] = ChannelRecorder(name, url, base_dir, **kwargs)

    def start_all(self):
        for rec in self.recorders.values():
            rec.start()

    def stop_all(self):
        for rec in self.recorders.values():
            rec.stop()

    def status_all(self) -> list[dict]:
        return [
            {"name": r.name, "url": r.url, "running": r.is_running()}
            for r in self.recorders.values()
        ]
