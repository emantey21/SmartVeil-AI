import argparse
import configparser
import logging
import signal
import sys

from recorder import RecorderManager
from viewer import view_single, view_grid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("smarthome")


def load_config(path: str) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read(path)
    return config


def cmd_record(config_path: str):
    config = load_config(config_path)
    manager = RecorderManager()

    settings = config["settings"]
    base_dir = settings.get("base_dir", "/home/gfsa/Desktop/shared_files/CCTV")
    segment_time = settings.getint("segment_time", 600)
    transport = settings.get("rtsp_transport", "tcp")

    for name, url in config["channels"].items():
        manager.add(name, url, base_dir, segment_time=segment_time, transport=transport)

    def shutdown(sig, frame):
        logger.info("Shutting down all recorders...")
        manager.stop_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    manager.start_all()
    logger.info("All channels recording. Press Ctrl+C to stop.")

    try:
        signal.pause()
    except AttributeError:
        import time
        while True:
            time.sleep(1)


def cmd_status(config_path: str):
    config = load_config(config_path)
    manager = RecorderManager()
    settings = config["settings"]
    base_dir = settings.get("base_dir", "/home/gfsa/Desktop/shared_files/CCTV")
    segment_time = settings.getint("segment_time", 600)
    transport = settings.get("rtsp_transport", "tcp")

    for name, url in config["channels"].items():
        manager.add(name, url, base_dir, segment_time=segment_time, transport=transport)

    manager.start_all()
    statuses = manager.status_all()
    for s in statuses:
        status = "RUNNING" if s["running"] else "STOPPED"
        print(f"[{status}] {s['name']} - {s['url']}")
    manager.stop_all()


def cmd_list_channels(config_path: str):
    config = load_config(config_path)
    for i, (name, url) in enumerate(config["channels"].items(), 1):
        print(f"  {i}. {name} -> {url}")


def cmd_app(config_path: str):
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        logger.error("PySide6 is required. Install: pip install pyside6")
        sys.exit(1)
    from app.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setStyleSheet("QToolTip { color: white; background: #333; border: 1px solid #555; }")
    win = MainWindow(config_path)
    win.show()
    sys.exit(app.exec())


def cmd_view(config_path: str, channel_name: str | None, grid: bool):
    config = load_config(config_path)
    transport = config["settings"].get("rtsp_transport", "tcp")
    channels = list(config["channels"].items())

    if grid:
        view_grid(channels, transport=transport)
        return

    if channel_name:
        if channel_name not in config["channels"]:
            logger.error("Unknown channel '%s'. Use 'channels' to list them.", channel_name)
            sys.exit(1)
        view_single(channel_name, config["channels"][channel_name], transport=transport)
    else:
        import itertools
        for name, url in channels:
            print(f"  {name}")
        name = input("Enter channel name: ").strip()
        if name not in config["channels"]:
            logger.error("Unknown channel '%s'", name)
            sys.exit(1)
        view_single(name, config["channels"][name], transport=transport)


def main():
    parser = argparse.ArgumentParser(
        description="SmartVeil AI - Intelligent CCTV Surveillance",
    )
    parser.add_argument(
        "-c", "--config",
        default="config.ini",
        help="Path to config file (default: config.ini)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("record", help="Start recording all channels")
    sub.add_parser("status", help="Show recording status")
    sub.add_parser("channels", help="List configured channels")

    view_parser = sub.add_parser("view", help="View live CCTV feed")
    view_parser.add_argument("channel", nargs="?", default=None, help="Channel name to view")
    view_parser.add_argument("--grid", "-g", action="store_true", help="Show all channels in a grid")

    sub.add_parser("app", help="Launch desktop GUI application")

    args = parser.parse_args()

    if args.command == "record":
        cmd_record(args.config)
    elif args.command == "status":
        cmd_status(args.config)
    elif args.command == "channels":
        cmd_list_channels(args.config)
    elif args.command == "view":
        cmd_view(args.config, args.channel, args.grid)
    elif args.command == "app":
        cmd_app(args.config)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
