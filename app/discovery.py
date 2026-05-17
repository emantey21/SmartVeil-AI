import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

STREAM_LABELS = {0: "Main", 1: "Sub", 2: "Mobile"}

QUICK_PATHS = [
    "/avstream/channel=1/stream=0.sdp",
    "/avstream/channel=1/stream=1.sdp",
    "/live",
    "/onvif1",
    "/h264",
    "/cam/realmonitor",
    "/streaming/channels/1",
    "/ch1/main/av_stream",
]


def quality_label(url: str) -> str:
    m = re.search(r'stream=(\d+)', url)
    if m:
        s = int(m.group(1))
        return STREAM_LABELS.get(s, f"Stream {s}")
    return "Stream"


def expand_urls(base_urls: list[str]) -> list[str]:
    expanded = set()
    for url in base_urls:
        expanded.add(url)
        ch = re.findall(r'channel=(\d+)', url)
        st = re.findall(r'stream=(\d+)', url)
        base = url
        if ch:
            base = re.sub(r'channel=\d+', 'channel={}', base)
            for c in range(1, 17):
                expanded.add(base.format(c))
        for e in list(expanded):
            if re.search(r'stream=\d+', e):
                sbase = re.sub(r'stream=\d+', 'stream={}', e)
                for s in range(3):
                    expanded.add(sbase.format(s))
    return list(expanded)


def probe_paths(ip: str, port: int, paths: list[str],
                timeout: float = 2.0) -> list[str]:
    found = []
    for path in paths:
        url = f"rtsp://{ip}:{port}{path}"
        try:
            s = socket.create_connection((ip, port), timeout=timeout)
            req = f"OPTIONS {url} RTSP/1.0\r\nCSeq: 1\r\n\r\n"
            s.sendall(req.encode())
            resp = s.recv(1024).decode("utf-8", errors="ignore")
            s.close()
            if "200 OK" in resp or "RTSP/1.0 200" in resp or "RTSP/1.0 401" in resp:
                found.append(url)
        except Exception:
            continue
    return found


def discover_network(subnet: str = "192.168.8.0/24",
                     ports: list[int] | None = None,
                     max_workers: int = 100, timeout: float = 0.8,
                     progress_callback=None,
                     extra_paths: list[str] | None = None) -> list[dict]:
    if ports is None:
        ports = [554]

    results = []
    net = ipaddress.ip_network(subnet, strict=False)
    hosts = [str(h) for h in net.hosts()]

    def check(ip):
        for port in ports:
            try:
                s = socket.create_connection((ip, port), timeout=timeout)
                s.close()
            except Exception:
                continue
            urls = probe_paths(ip, port, QUICK_PATHS, timeout)
            if urls:
                return {"ip": ip, "port": port, "urls": urls}
        return None

    done = 0
    total = len(hosts)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_map = {pool.submit(check, ip): ip for ip in hosts}
        for f in as_completed(fut_map):
            done += 1
            if progress_callback:
                progress_callback(done, total)
            result = f.result()
            if result:
                results.append(result)

    if extra_paths:
        extra = expand_urls(extra_paths)
        for r in results:
            more = probe_paths(r["ip"], r["port"], extra, timeout)
            for url in more:
                if url not in r["urls"]:
                    r["urls"].append(url)

    return results
