#!/usr/bin/env python3
"""Build README and Pages showcase images, captions and demo video from the static atlas."""

from __future__ import annotations

import http.server
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
EXIFTOOL = "/opt/homebrew/bin/exiftool"
MEDIA = ROOT / "docs" / "media"
SHOWCASE = ROOT / "showcase-media"
SITE = ROOT / "docs" / "site"
WINDOW = "1400,900"

STEPS: list[tuple[str, str]] = [
    ("Hero: scheduled access and verification summary.", ""),
    ("Atlas: 45-minute reach across dissemination areas.", "#atlas"),
    ("Hourly citywide profiles for 30, 45 and 60 minutes.", "#atlas"),
    ("Route deletions ranked by 45-minute population loss.", "#routes"),
    ("Method: oracle check, exact reuse and decomposition.", "#method"),
    ("Stated limits on walking, samples and frozen exceptions.", "#limits"),
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
    if not EXIFTOOL.exists():
        return
    for p in paths:
        if p.exists() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            subprocess.run([EXIFTOOL, "-all=", "-overwrite_original", str(p)], check=True)


def vtt_timestamp(sec: float) -> str:
    m, s = divmod(sec, 60)
    return f"00:{int(m):02d}:{s:06.3f}".replace(".", ",")


def export_chart_pngs(port: int) -> list[Path]:
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
    chrome_screenshot(f"http://127.0.0.1:{port}/index.html#atlas", atlas)
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

    raw = SHOWCASE / "demo_raw.mp4"
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
            "scale=1280:720:force_original_aspect_ratio=decrease,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-map_metadata",
            "-1",
            str(raw),
        ],
        check=True,
        capture_output=True,
    )

    vtt_esc = str(vtt).replace(":", "\\:")
    burned = SHOWCASE / "demo_burned.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(raw),
            "-vf",
            f"subtitles={vtt_esc}:force_style='Fontsize=22,PrimaryColour=&Hffffff&,"
            "OutlineColour=&H000000&,BorderStyle=3'",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-map_metadata",
            "-1",
            str(burned),
        ],
        check=True,
        capture_output=True,
    )
    shutil.move(str(burned), str(mp4))
    raw.unlink(missing_ok=True)
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


def main() -> int:
    MEDIA.mkdir(parents=True, exist_ok=True)
    port = free_port()
    server = serve_site(port)
    time.sleep(0.5)

    hero = MEDIA / "hero-atlas.png"
    chrome_screenshot(f"http://127.0.0.1:{port}/index.html#routes", hero)

    frames: list[Path] = []
    vtt_lines = ["WEBVTT", ""]
    t = 0.0
    hold = 5.0
    for i, (caption, fragment) in enumerate(STEPS, start=1):
        frame = MEDIA / f"step-{i:02d}.png"
        url = f"http://127.0.0.1:{port}/index.html{fragment}"
        chrome_screenshot(url, frame)
        frames.append(frame)
        vtt_lines.append(f"{vtt_timestamp(t)} --> {vtt_timestamp(t + hold)}")
        vtt_lines.append(caption)
        vtt_lines.append("")
        t += hold

    vtt = MEDIA / "demo.en.vtt"
    vtt.write_text("\n".join(vtt_lines), encoding="utf-8")

    mp4 = SHOWCASE / "demo.mp4"
    poster = MEDIA / "demo-poster.png"
    preview = MEDIA / "demo-preview.gif"
    build_video(frames, vtt, mp4, poster, preview)

    charts = export_chart_pngs(port)
    strip_images([hero, poster, preview, *frames, *charts])
    server.shutdown()
    size_mb = mp4.stat().st_size / (1024 * 1024)
    if size_mb > 10:
        print(f"Warning: demo.mp4 is {size_mb:.1f} MB", file=sys.stderr)
    print(f"Done: hero, {len(frames)} frames, {len(charts)} charts, video {size_mb:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
