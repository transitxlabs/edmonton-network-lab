"""Build README and Pages showcase images, captions and demo video from the static atlas."""

from __future__ import annotations

import atexit
import base64
import hashlib
import http.server
import json
import os
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Self


class DevToolsWebSocket:
    """Minimal WebSocket client for Chrome DevTools Protocol (stdlib only)."""

    def __init__(self, url: str, timeout: float = 10.0) -> None:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += self._sock.recv(4096)
        accept = None
        for line in response.decode(errors="replace").split("\r\n"):
            if line.lower().startswith("sec-websocket-accept:"):
                accept = line.split(":", 1)[1].strip()
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        if accept != expected:
            raise RuntimeError("WebSocket handshake failed")

    def send(self, payload: str) -> None:
        data = payload.encode()
        mask = secrets.token_bytes(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        frame = bytearray([0x81])
        length = len(data)
        if length < 126:
            frame.append(0x80 | length)
        elif length < (1 << 16):
            frame.append(0x80 | 126)
            frame.extend(struct.pack(">H", length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack(">Q", length))
        frame.extend(mask)
        frame.extend(masked)
        self._sock.sendall(frame)

    def recv(self) -> str:
        while True:
            header = self._recv_exact(2)
            opcode = header[0] & 0x0F
            masked = header[1] & 0x80
            length = header[1] & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x1:
                return payload.decode()
            if opcode == 0x8:
                raise RuntimeError("WebSocket closed")

    def _recv_exact(self, nbytes: int) -> bytes:
        chunks: list[bytes] = []
        got = 0
        while got < nbytes:
            part = self._sock.recv(nbytes - got)
            if not part:
                raise RuntimeError("WebSocket connection closed")
            chunks.append(part)
            got += len(part)
        return b"".join(chunks)

    def close(self) -> None:
        self._sock.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


ROOT = Path(__file__).resolve().parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def find_ffmpeg() -> str:
    seen: set[str] = set()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / "ffmpeg"
        resolved = str(candidate.resolve()) if candidate.exists() else ""
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        proc = subprocess.run([resolved, "-filters"], capture_output=True, text=True, check=False)
        if "drawtext" in proc.stdout:
            return resolved
    raise RuntimeError("ffmpeg with drawtext support not found on PATH")


FFMPEG = find_ffmpeg()
EXIFTOOL = shutil.which("exiftool")
MEDIA = ROOT / "docs" / "media"
SHOWCASE = ROOT / "showcase-media"
SITE = ROOT / "docs" / "site"
WINDOW = "1400,900"
CAPTION_FONT = 28

# caption, page path, CSS selector, text that must appear in the viewport
STEPS: list[tuple[str, str, str, str]] = [
    (
        "Hero: scheduled access and verification summary.",
        "/index.html",
        "section.hero",
        "What changes when",
    ),
    (
        "Atlas: 45-minute reach across dissemination areas.",
        "/index.html",
        "#atlas .atlas-grid",
        "Citywide 45-minute access",
    ),
    (
        "Hourly citywide profiles for 30, 45 and 60 minutes.",
        "/index.html",
        "#atlas figure.wide",
        "Lines connect evaluated",
    ),
    (
        "Route deletions ranked by 45-minute population loss.",
        "/index.html",
        "#routes .table-wrap",
        "Capital Line",
    ),
    (
        "Method: oracle check, exact reuse and decomposition.",
        "/index.html",
        "#method",
        "Independent calculation",
    ),
    (
        "Stated limits on walking, samples and frozen exceptions.",
        "/index.html",
        "#limits",
        "Scheduled access, with stated limits",
    ),
]


def chrome_screenshot(url: str, out: Path, window: str = WINDOW) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            CHROME,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={window}",
            f"--screenshot={out}",
            url,
        ],
        check=True,
        capture_output=True,
    )


class HeadlessChrome:
    def __init__(self, window: str = WINDOW) -> None:
        self.window = window
        self.port = free_port()
        self._proc = subprocess.Popen(
            [
                CHROME,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--window-size={window}",
                f"--remote-debugging-port={self.port}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Its own process group, so close() stops Chrome and every helper it started.
            start_new_session=True,
        )
        # A backstop: a browser left open by an early exit is closed when Python exits.
        atexit.register(self.close)
        self._wait_for_browser()

    def _wait_for_browser(self) -> None:
        version_url = f"http://127.0.0.1:{self.port}/json/version"
        for _ in range(80):
            try:
                with urllib.request.urlopen(version_url, timeout=1):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("Chrome remote debugging did not start")

    def close(self) -> None:
        """Stop Chrome's whole process group; safe to call more than once."""
        if self._proc.poll() is not None:
            return
        for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
            try:
                os.killpg(self._proc.pid, sig)
            except ProcessLookupError:
                return
            try:
                self._proc.wait(timeout=wait)
                return
            except subprocess.TimeoutExpired:
                continue

    def screenshot_section(
        self,
        page_url: str,
        selector: str,
        out: Path,
        step_id: int = 0,
        must_contain: str = "",
    ) -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        sel = json.dumps(selector)
        nav_url = f"{page_url}?__step={step_id}&__showcase={urllib.parse.quote(selector, safe='')}"
        open_url = f"http://127.0.0.1:{self.port}/json/new?{urllib.parse.quote(nav_url, safe='')}"
        open_req = urllib.request.Request(open_url, method="PUT")
        with urllib.request.urlopen(open_req, timeout=30) as resp:
            target = json.loads(resp.read())
        wait_js = (
            "(() => Promise.all([...document.images].map((img) =>"
            " img.complete ? Promise.resolve() :"
            " new Promise((r) => { img.onload = img.onerror = r; }))))()"
        )
        crop_js = (
            f"(() => {{ const el = document.querySelector({sel});"
            " if (!el) throw new Error('missing selector');"
            " const vh = window.innerHeight || 900;"
            " const docTop = el.getBoundingClientRect().top + window.scrollY;"
            " const top = Math.max(0, docTop - 72);"
            " return {left: 0, top, width: document.documentElement.clientWidth || 1400,"
            " height: Math.min(vh, document.body.scrollHeight - top)}; })()"
        )
        msg_id = 0
        with DevToolsWebSocket(target["webSocketDebuggerUrl"]) as ws:

            def call(method: str, params: dict | None = None) -> dict:
                nonlocal msg_id
                msg_id += 1
                payload = {"id": msg_id, "method": method, "params": params or {}}
                ws.send(json.dumps(payload))
                while True:
                    raw = ws.recv()
                    data = json.loads(raw)
                    if data.get("id") == msg_id:
                        if "error" in data:
                            raise RuntimeError(data["error"])
                        return data.get("result", {})

            call("Page.enable")
            call("Runtime.enable")
            call("Page.navigate", {"url": nav_url})
            time.sleep(2.0)
            for _ in range(80):
                state = call(
                    "Runtime.evaluate",
                    {"expression": "document.readyState", "returnByValue": True},
                )
                if state.get("result", {}).get("value") == "complete":
                    break
                time.sleep(0.1)
            wait_sel = (
                f"(() => {{ const el = document.querySelector({sel}); return Boolean(el); }})()"
            )
            for _ in range(40):
                found = call(
                    "Runtime.evaluate",
                    {"expression": wait_sel, "returnByValue": True},
                )
                if found.get("result", {}).get("value"):
                    break
                time.sleep(0.1)
            call("Runtime.evaluate", {"expression": wait_js, "awaitPromise": True})
            crop = call(
                "Runtime.evaluate",
                {"expression": crop_js, "returnByValue": True, "awaitPromise": False},
            )
            if crop.get("exceptionDetails"):
                raise RuntimeError(crop["exceptionDetails"])
            box = crop["result"]["value"]
            if must_contain:
                needle = json.dumps(must_contain)
                in_crop = (
                    f"(() => {{ const needle = {needle};"
                    f" const top = {box['top']}; const bottom = top + {box['height']};"
                    " const nodes = document.querySelectorAll('h1,h2,h3,p,td,th,figcaption,li,span');"
                    " for (const node of nodes) {"
                    " if (!(node.innerText || '').includes(needle)) continue;"
                    " const y = node.getBoundingClientRect().top + window.scrollY;"
                    " if (y >= top && y < bottom) return true;"
                    " } return false; })()"
                )
                if (
                    not call(
                        "Runtime.evaluate",
                        {"expression": in_crop, "returnByValue": True},
                    )
                    .get("result", {})
                    .get("value")
                ):
                    raise RuntimeError(f"expected text not in crop for {selector}: {must_contain}")
            shot = call(
                "Page.captureScreenshot",
                {"format": "png", "fromSurface": True, "captureBeyondViewport": True},
            )
            full_png = SHOWCASE / f"_capture_full_{step_id}.png"
            full_png.write_bytes(base64.b64decode(shot["data"]))
            left = int(box["left"])
            top = int(box["top"])
            width = int(box["width"])
            height = int(box["height"])
            subprocess.run(
                [
                    FFMPEG,
                    "-y",
                    "-i",
                    str(full_png),
                    "-vf",
                    f"crop={width}:{height}:{left}:{top}",
                    str(out),
                ],
                check=True,
                capture_output=True,
            )
            full_png.unlink(missing_ok=True)
        close_url = f"http://127.0.0.1:{self.port}/json/close/{target['id']}"
        try:
            urllib.request.urlopen(close_url, timeout=5)
        except OSError:
            pass


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_site(port: int) -> http.server.HTTPServer:
    os.chdir(SITE)
    server = http.server.HTTPServer(("127.0.0.1", port), http.server.SimpleHTTPRequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def strip_images(paths: list[Path]) -> None:
    exif = shutil.which("exiftool")
    if not exif:
        return
    for p in paths:
        if p.exists() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            subprocess.run([exif, "-all=", "-overwrite_original", str(p)], check=True)


def vtt_timestamp(sec: float) -> str:
    m, s = divmod(sec, 60)
    return f"00:{int(m):02d}:{s:06.3f}"  # WebVTT uses a full stop before the milliseconds


def escape_drawtext(text: str) -> str:
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\\'")
    return text


def wrap_caption(text: str, max_len: int = 52) -> str:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = (" ".join(current + [word])).strip()
        if len(trial) > max_len and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines[:2])


def burn_caption_on_frame_from_str(frame: Path, caption: str, captioned: Path) -> None:
    # The caption goes through a text file, so its line break is a real one and nothing in it is escaped or expanded.
    with tempfile.TemporaryDirectory() as tmp:
        text_file = Path(tmp) / "caption.txt"
        text_file.write_text(wrap_caption(caption), encoding="utf-8")
        vf = (
            f"drawtext=textfile='{escape_drawtext(str(text_file))}':expansion=none:"
            f"fontsize={CAPTION_FONT}:fontcolor=white:"
            "box=1:boxcolor=black@0.78:boxborderw=14:"
            "line_spacing=8:x=(w-text_w)/2:y=h-th-36"
        )
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-i",
                str(frame),
                "-vf",
                vf,
                "-map_metadata",
                "-1",
                str(captioned),
            ],
            check=True,
            capture_output=True,
        )


def export_chart_pngs(port: int, browser: HeadlessChrome) -> list[Path]:
    out: list[Path] = []
    for stem, window in (
        ("route-ranking", "1200,500"),
        ("day-profile", "1200,500"),
    ):
        target = MEDIA / f"chart-{stem}.png"
        chrome_screenshot(
            f"file://{SITE / f'{stem}.svg'}",
            target,
            window=window,
        )
        out.append(target)
    arch = ROOT / "scripts" / "showcase_architecture.html"
    chrome_screenshot(f"file://{arch}", MEDIA / "architecture-flow.png", window="1200,220")
    out.append(MEDIA / "architecture-flow.png")
    atlas = MEDIA / "example-access-map.png"
    browser.screenshot_section(
        f"http://127.0.0.1:{port}/index.html",
        "#atlas .atlas-grid",
        atlas,
        step_id=90,
        must_contain="Citywide 45-minute access",
    )
    out.append(atlas)
    return out


def build_video(frames: list[Path], vtt: Path, mp4: Path, poster: Path, preview: Path) -> None:
    SHOWCASE.mkdir(parents=True, exist_ok=True)
    concat = SHOWCASE / "concat.txt"
    with concat.open("w") as f:
        for frame in frames:
            f.write(f"file '{frame}'\n")
            f.write("duration 5\n")
        f.write(f"file '{frames[-1]}'\n")

    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-vf",
            "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-map_metadata",
            "-1",
            str(mp4),
        ],
        check=True,
        capture_output=True,
    )
    concat.unlink(missing_ok=True)

    subprocess.run(
        [FFMPEG, "-y", "-i", str(mp4), "-vframes", "1", "-map_metadata", "-1", str(poster)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(mp4),
            "-vf",
            "fps=8,scale=640:-1:flags=lanczos",
            "-map_metadata",
            "-1",
            str(preview),
        ],
        check=True,
        capture_output=True,
    )


def _exit_on_signal(signum: int, frame: object) -> None:
    # SIGTERM becomes a normal exit, so main's finally block closes the browser and the server.
    raise SystemExit(128 + signum)


def main() -> int:
    signal.signal(signal.SIGTERM, _exit_on_signal)
    MEDIA.mkdir(parents=True, exist_ok=True)
    port = free_port()
    server = serve_site(port)
    browser: HeadlessChrome | None = None
    try:
        time.sleep(0.5)

        browser = HeadlessChrome()
        base = f"http://127.0.0.1:{port}"

        # The hero is the top of the atlas page (its question and headline counts), as the README's alt text describes.
        hero = MEDIA / "hero-atlas.png"
        chrome_screenshot(f"{base}/index.html", hero)

        frames: list[Path] = []
        captioned_frames: list[Path] = []
        vtt_lines = ["WEBVTT", ""]
        t = 0.0
        hold = 5.0
        for i, (caption, path, selector, marker) in enumerate(STEPS, start=1):
            frame = MEDIA / f"step-{i:02d}.png"
            browser.screenshot_section(
                f"{base}{path}", selector, frame, step_id=i, must_contain=marker
            )
            frames.append(frame)
            captioned = MEDIA / f"step-{i:02d}-captioned.png"
            burn_caption_on_frame_from_str(frame, caption, captioned)
            captioned_frames.append(captioned)
            vtt_lines.append(f"{vtt_timestamp(t)} --> {vtt_timestamp(t + hold)}")
            vtt_lines.append(caption)
            vtt_lines.append("")
            t += hold

        vtt = MEDIA / "demo.en.vtt"
        vtt.write_text("\n".join(vtt_lines), encoding="utf-8")

        mp4 = SHOWCASE / "demo.mp4"
        poster = MEDIA / "demo-poster.png"
        preview = MEDIA / "demo-preview.gif"
        build_video(captioned_frames, vtt, mp4, poster, preview)

        charts = export_chart_pngs(port, browser)
        strip_images([hero, poster, preview, *frames, *captioned_frames, *charts])
    finally:
        if browser is not None:
            browser.close()
        server.shutdown()
    size_mb = mp4.stat().st_size / (1024 * 1024)
    if size_mb > 10:
        print(f"Warning: demo.mp4 is {size_mb:.1f} MB", file=sys.stderr)
    print(f"Done: hero, {len(frames)} frames, {len(charts)} charts, video {size_mb:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
