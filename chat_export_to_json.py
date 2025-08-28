#!/usr/bin/env python3
#
# Streaming extractor for potentially huge single-line assignments in ChatGPT chat.html:
#
#     var jsonData = [ ... ];
#     var assetsJson = { ... };
#
# Writes 'data.json' and 'assets.json' (paths configurable). Trims everything up to and
# including "=", skips immediate spaces/tabs, and drops the trailing ";" (plus any
# trailing spaces or CR) before the newline. Handles files without a final newline.
#
# Copyright 2025 7th software Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations
import argparse
import sys
from collections import deque
from pathlib import Path
from typing import Optional

SPACE_TABS = b" \t"
SPACE = ord(b" ")
TAB = ord(b"\t")
NEWLINE = ord(b"\n")
CR = ord(b"\r")
SEMI = ord(b";")
EQUALS = ord(b"=")


def _which_assignment(head: bytes) -> Optional[str]:
    """
    Determine if the bytes up to (but not including) '=' are one of:
      jsonData or assetsJson, allowing optional var/let/const and window. prefix.
    """

    b = head.lstrip(SPACE_TABS)

    # Optional keyword
    for kw in (b"var", b"let", b"const"):
        if b.startswith(kw):
            b = b[len(kw):].lstrip(SPACE_TABS)
            break

    # Optional window. prefix
    if b.startswith(b"window."):
        b = b[len(b"window."):].lstrip(SPACE_TABS)

    if b.startswith(b"jsonData"):
        return "json"
    if b.startswith(b"assetsJson"):
        return "assets"
    return None


def _open_out(path: Path, overwrite: bool):
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}. Use --overwrite to allow.")
    return path.open("wb")


def extract_chat_html(
    html_path: Path,
    data_out: Optional[Path] = None,
    assets_out: Optional[Path] = None,
    *,
    overwrite: bool = False,
    chunk_size: int = 1024 * 1024,
    trailing_buffer: int = 8192,
) -> tuple[Optional[Path], Optional[Path]]:
    """
    Stream-parse `chat.html` and write the values of jsonData and assetsJson to files.

    Returns (data_path, assets_path); either may be None if not found.
    """

    html_path = Path(html_path)
    if not html_path.is_file():
        raise FileNotFoundError(f"Input HTML not found: {html_path}")

    if data_out is None:
        data_out = html_path.with_name("data.json")
    if assets_out is None:
        assets_out = html_path.with_name("assets.json")

    found_json = False
    found_assets = False

    out_fp = None
    capturing = None  # None | "json" | "assets" | "skipline"
    started_content = False

    # Keep only the tail so we can trim semicolon and trailing whitespace
    hold = deque(maxlen=max(1024, trailing_buffer))

    # Buffer from the last newline up to the '=' to decide which var we saw
    headbuf = bytearray()

    with html_path.open("rb") as f:
        while True:
            chunk = f.read(max(64 * 1024, chunk_size))
            if not chunk:
                break

            for b in chunk:
                if capturing is None:
                    headbuf.append(b)

                    if b == NEWLINE:
                        headbuf.clear()

                    elif b == EQUALS:
                        var = _which_assignment(bytes(headbuf[:-1]))
                        if var is None:
                            headbuf.clear()
                            capturing = "skipline"
                        else:
                            if var == "json" and not found_json:
                                out_fp = _open_out(data_out, overwrite)
                                capturing = "json"
                            elif var == "assets" and not found_assets:
                                out_fp = _open_out(assets_out, overwrite)
                                capturing = "assets"
                            else:
                                headbuf.clear()
                                capturing = "skipline"
                                continue
                            started_content = False
                            hold.clear()
                            headbuf.clear()

                elif capturing == "skipline":
                    if b == NEWLINE:
                        capturing = None
                        headbuf.clear()

                else:
                    # Capturing JSON or assets content
                    if not started_content:
                        # Skip only immediate spaces/tabs after '='
                        if b in (SPACE, TAB):
                            continue
                        started_content = True

                    if b == NEWLINE:
                        # Trim trailing spaces/tabs/CR
                        while hold and hold[-1] in (SPACE, TAB, CR):
                            hold.pop()
                        # Drop trailing semicolon
                        if hold and hold[-1] == SEMI:
                            hold.pop()

                        # Flush remaining
                        if hold:
                            out_fp.write(bytes(hold))
                        out_fp.close()
                        out_fp = None

                        if capturing == "json":
                            found_json = True
                        else:
                            found_assets = True

                        capturing = None
                        headbuf.clear()
                        hold.clear()
                        started_content = False
                    else:
                        hold.append(b)
                        if len(hold) == hold.maxlen:
                            out_fp.write(bytes([hold.popleft()]))

        # EOF without final newline while capturing
        if capturing in ("json", "assets") and out_fp is not None:
            while hold and hold[-1] in (SPACE, TAB, CR):
                hold.pop()
            if hold and hold[-1] == SEMI:
                hold.pop()
            if hold:
                out_fp.write(bytes(hold))
            out_fp.close()
            if capturing == "json":
                found_json = True
            else:
                found_assets = True

    return (data_out if found_json else None, assets_out if found_assets else None)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Extract jsonData and assetsJson from a ChatGPT chat.html export, streaming safely.")
    p.add_argument("html", type=Path, help="Path to chat.html")
    p.add_argument("--data-out", type=Path, help="Where to write data.json (default: alongside HTML)")
    p.add_argument("--assets-out", type=Path, help="Where to write assets.json (default: alongside HTML)")
    p.add_argument("--overwrite", action="store_true", help="Allow overwriting existing output files")
    p.add_argument("--chunk-size", type=int, default=1024*1024, help="Read chunk size in bytes (default 1 MiB)")
    p.add_argument("--trailing-buffer", type=int, default=8192, help="Bytes to retain for trimming final ';' (default 8192)")

    args = p.parse_args(argv)

    try:
        data_path, assets_path = extract_chat_html(
            args.html,
            data_out=args.data_out,
            assets_out=args.assets_out,
            overwrite=args.overwrite,
            chunk_size=max(64*1024, args.chunk_size),
            trailing_buffer=max(1024, args.trailing_buffer),
        )
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1

    if data_path:
        print(f"Wrote: {data_path}")
    else:
        print("jsonData not found.")

    if assets_path:
        print(f"Wrote: {assets_path}")
    else:
        print("assetsJson not found.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
