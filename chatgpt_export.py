#!/usr/bin/env python3
#
# Example use cases for the 'chatgpt_export' module.
#
# Copyright (c) 2025, 7th software Ltd.
# All rights reserved.

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple, Union


# Type annotation macro for JSON objects
Json = Union[Dict[str, Any], List[Any]]


def _to_datetime(value: Any) -> Optional[datetime]:
    """
    Best-effort conversion of a timestamp-like value to a timezone-aware UTC datetime.

    Accepts:
      - UNIX epoch seconds (int/float or numeric string)
      - ISO8601 strings

    Returns None if parsing fails or value is missing.
    """

    if value is None:
        return None

    # Try numeric epoch seconds first
    try:
        # Handles strings like "1691234567.123" or numbers
        ts = float(value)
        if ts > 0:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        pass

    # Try ISO 8601 parse via fromisoformat (supports "YYYY-MM-DDTHH:MM:SS.mmm+00:00")
    if isinstance(value, str):
        try:
            # Replace 'Z' with '+00:00' for Python compatibility
            v = value.replace("Z", "+00:00") if value.endswith("Z") else value
            dt = datetime.fromisoformat(v)
            # Assume naive means UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None


def _safe_get(dct: Dict[str, Any], path: Iterable[Union[str, int]], default=None):
    """Safely get a nested value by following a sequence of keys/indexes."""

    cur: Any = dct
    for key in path:
        try:
            if isinstance(key, int) and isinstance(cur, list):
                cur = cur[key]
            elif isinstance(key, str) and isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return default
        except Exception:
            return default
        if cur is None:
            return default
    return cur


@dataclass(frozen=True)
class AssetRef:
    """Reference to an asset pointer plus a resolved URL if available."""

    asset_pointer: str
    content_type: Optional[str] = None
    url: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MessagePart:
    """One part of a message: text, transcript, or an asset."""

    kind: str  # "text" | "transcript" | "asset"
    text: Optional[str] = None
    asset: Optional[AssetRef] = None


@dataclass(frozen=True)
class Message:
    id: str
    author_raw: str
    author_display: str
    create_time: Optional[datetime]
    content_type: Optional[str]
    parts: Tuple[MessagePart, ...]
    metadata: Dict[str, Any]

    def text_content(self, join_with: str = "\n") -> str:
        """Concatenate textual parts for searching or display."""

        texts: List[str] = []
        for p in self.parts:
            if p.kind == "text" and p.text:
                texts.append(p.text)
            elif p.kind == "transcript" and p.text:
                texts.append(p.text)
        return join_with.join(texts)


@dataclass(frozen=True)
class ConversationInfo:
    id: str
    title: str
    create_time: Optional[datetime]
    update_time: Optional[datetime]


class ChatGPTExport:
    """
    Parser and query helper for ChatGPT Data Export files.

    Typical usage:
        exp = ChatGPTExport.from_files("data.json", "assets.json")
        for info in exp.list_conversations():
            print(info.title, info.create_time)

        # Get the current-path messages (as in the HTML export) for a conversation:
        for msg in exp.iter_messages(info.id):
            print(msg.author_display, msg.create_time, msg.text_content())

        # Search text across all conversations:
        matches = exp.search_messages("regex or plain text", regex=False)
    """

    def __init__(self, data: List[Dict[str, Any]], assets: Optional[Dict[str, str]] = None):
        if not isinstance(data, list):
            raise TypeError("`data` must be a list of conversation dicts (parsed from data.json).")
        self._conversations: List[Dict[str, Any]] = data
        self._by_id: Dict[str, Dict[str, Any]] = {}
        for conv in self._conversations:
            cid = str(conv.get("conversation_id") or conv.get("id") or conv.get("uuid") or "")
            if cid:
                self._by_id[cid] = conv
        self._assets_map: Dict[str, str] = assets or {}

    # ------------------------ Construction helpers ------------------------

    @classmethod
    def from_files(cls, data_path: Union[str, Path], assets_path: Optional[Union[str, Path]] = None) -> "ChatGPTExport":
        """Load from disk given paths to data.json and assets.json."""

        dp = Path(data_path)
        ap = Path(assets_path) if assets_path is not None else None
        with dp.open("r", encoding="utf-8") as f:
            data = json.load(f)
        assets: Optional[Dict[str, str]] = None
        if ap is not None and ap.exists():
            with ap.open("r", encoding="utf-8") as f:
                assets = json.load(f)
        return cls(data=data, assets=assets)

    # ------------------------ Conversations -------------------------

    def list_conversations(self) -> List[ConversationInfo]:
        """Return basic info for each conversation."""

        out: List[ConversationInfo] = []
        for conv in self._conversations:
            title = str(conv.get("title") or "Untitled").strip()
            conv_id = str(conv.get("conversation_id") or conv.get("id") or conv.get("uuid") or title)
            ctime = _to_datetime(conv.get("create_time"))
            utime = _to_datetime(conv.get("update_time"))
            out.append(ConversationInfo(id=conv_id, title=title, create_time=ctime, update_time=utime))
        return out

        # Note: order is the same as in the JSON file (usually newest first).

    def get_conversation(self, conv_ref: Union[str, int]) -> Dict[str, Any]:
        """Fetch the raw conversation dict by id or by index (0-based)."""

        if isinstance(conv_ref, int):
            try:
                return self._conversations[conv_ref]
            except IndexError:
                raise KeyError(f"No conversation at index {conv_ref}.")
        conv = self._by_id.get(str(conv_ref))
        if conv is None:
            # Fallback: try title match (exact first, then case-insensitive)
            for c in self._conversations:
                if c.get("title").strip() == conv_ref:
                    return c
            for c in self._conversations:
                if isinstance(conv_ref, str) and str(c.get("title").strip() or "").lower() == conv_ref.lower():
                    return c
            raise KeyError(f"Conversation not found: {conv_ref}")
        return conv

    # -------------------------- Messages ----------------------------

    def _normalise_author(self, message: Dict[str, Any]) -> Tuple[str, str]:
        """Map raw roles to a user-friendly display, following the HTML export logic."""

        author_raw = str(_safe_get(message, ["author", "role"], "unknown"))
        display = author_raw
        if author_raw in {"assistant", "tool"}:
            display = "ChatGPT"
        elif author_raw == "system" and bool(_safe_get(message, ["metadata", "is_user_system_message"], False)):
            display = "Custom user info"
        return author_raw, display

    def _collect_parts(self, msg: Dict[str, Any]) -> List[MessagePart]:
        """
        Convert the message.content.parts into a neutral structure.

        Mirrors the HTML's behaviour for text, audio_transcription, and asset pointers.
        """

        parts_out: List[MessagePart] = []
        content: Dict[str, Any] = msg.get("content") or {}
        ctype: str = content.get("content_type") or ""
        raw_parts: List[Any] = content.get("parts") or []

        # Only text-like content types are iterated in the HTML viewer.
        if ctype not in {"text", "multimodal_text"}:
            return parts_out

        for part in raw_parts:
            # 1) Plain string text
            if isinstance(part, str) and part.strip():
                parts_out.append(MessagePart(kind="text", text=part))
                continue

            if not isinstance(part, dict):
                # Unrecognised structure: skip conservatively
                continue

            ptype = part.get("content_type")

            # 2) Audio transcription
            if ptype == "audio_transcription":
                t = part.get("text")
                if isinstance(t, str) and t.strip():
                    parts_out.append(MessagePart(kind="transcript", text=t))
                continue

            # 3) Direct asset pointers
            if ptype in {"audio_asset_pointer", "image_asset_pointer", "video_container_asset_pointer"}:
                ap = part.get("asset_pointer") or part.get("asset") or ""
                url = self._assets_map.get(ap)
                parts_out.append(MessagePart(kind="asset", asset=AssetRef(asset_pointer=ap, content_type=ptype, url=url, raw=part)))
                continue

            # 4) Real-time A/V pointer aggregates
            if ptype == "real_time_user_audio_video_asset_pointer":
                # Audio pointer
                ap_audio = _safe_get(part, ["audio_asset_pointer", "asset_pointer"])
                if isinstance(ap_audio, str) and ap_audio:
                    url = self._assets_map.get(ap_audio)
                    parts_out.append(MessagePart(kind="asset", asset=AssetRef(asset_pointer=ap_audio, content_type="audio_asset_pointer", url=url, raw=part)))

                # Video container pointer
                ap_video = _safe_get(part, ["video_container_asset_pointer", "asset_pointer"])
                if isinstance(ap_video, str) and ap_video:
                    url = self._assets_map.get(ap_video)
                    parts_out.append(MessagePart(kind="asset", asset=AssetRef(asset_pointer=ap_video, content_type="video_container_asset_pointer", url=url, raw=part)))

                # Frames pointers
                frames = part.get("frames_asset_pointers") or []
                for fp in frames:
                    if isinstance(fp, dict):
                        ap_frame = fp.get("asset_pointer") or ""
                        if ap_frame:
                            url = self._assets_map.get(ap_frame)
                            parts_out.append(MessagePart(kind="asset", asset=AssetRef(asset_pointer=ap_frame, content_type="image_asset_pointer", url=url, raw=fp)))
                    elif isinstance(fp, str) and fp:
                        url = self._assets_map.get(fp)
                        parts_out.append(MessagePart(kind="asset", asset=AssetRef(asset_pointer=fp, content_type="image_asset_pointer", url=url, raw={"asset_pointer": fp})))
                continue

            # Otherwise ignore; we keep behaviour aligned with the HTML exporter.
        return parts_out

    def _build_current_path(self, conv: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Reconstruct the linear 'current path' of messages like the HTML export does.

        Starts from conversation.current_node and follows parent pointers to the root.
        Skips messages that do not conform to the HTML viewer's filters.
        """

        mapping: Dict[str, Any] = conv.get("mapping") or {}
        cur = conv.get("current_node")
        chain: List[Dict[str, Any]] = []

        while cur is not None:
            node = mapping.get(cur)
            if not isinstance(node, dict):
                break

            msg = node.get("message")
            content = _safe_get(node, ["message", "content"])
            parts = _safe_get(content or {}, ["parts"]) or []

            # Keep parity with HTML conditions
            displayable = False
            if msg and content and isinstance(parts, list) and len(parts) > 0:
                role = _safe_get(msg, ["author", "role"])
                if role != "system" or bool(_safe_get(msg, ["metadata", "is_user_system_message"], False)):
                    ctype = content.get("content_type")
                    if ctype in {"text", "multimodal_text"}:
                        displayable = True

            if displayable:
                chain.append(node)

            cur = node.get("parent")

        chain.reverse()
        return chain

    def _node_to_message(self, node: Dict[str, Any]) -> Message:
        """Convert a mapping node to a normalised Message."""

        msg = node.get("message") or {}
        author_raw, author_display = self._normalise_author(msg)
        create_time = _to_datetime(msg.get("create_time"))
        parts = tuple(self._collect_parts(msg))
        content_type = _safe_get(msg, ["content", "content_type"])
        mid = str(msg.get("id") or node.get("id") or "")
        metadata = msg.get("metadata") or {}
        return Message(
            id=mid,
            author_raw=author_raw,
            author_display=author_display,
            create_time=create_time,
            content_type=content_type,
            parts=parts,
            metadata=metadata,
        )

    def iter_messages(self, conv_ref: Union[str, int], mode: str = "current_path") -> Generator[Message, None, None]:
        """
        Yield Message objects for a conversation.

        mode:
          - "current_path" (default): follows the same linear path as the HTML page.
          - "chronological_all": walk all mapping nodes with a message and sort by create_time then DFS order.
        """

        conv = self.get_conversation(conv_ref)

        if mode == "current_path":
            for node in self._build_current_path(conv):
                yield self._node_to_message(node)
            return

        if mode == "chronological_all":
            mapping: Dict[str, Any] = conv.get("mapping") or {}
            nodes: List[Dict[str, Any]] = []

            # Collect nodes that have a displayable message (loosely; accept any content_type)
            for node in mapping.values():
                msg = node.get("message")
                if not msg:
                    continue
                content = _safe_get(msg, ["content"]) or {}
                parts = content.get("parts") or []
                if not parts:
                    continue
                nodes.append(node)

            # Sort by create_time (None at the end), then by id for stability
            def sort_key(n: Dict[str, Any]) -> Tuple[int, float, str]:
                m = n.get("message") or {}
                ct = m.get("create_time")
                try:
                    ts = float(ct)
                except Exception:
                    ts = float("inf")
                return (0 if ct is not None else 1, ts, str(m.get("id") or n.get("id") or ""))

            nodes.sort(key=sort_key)
            for node in nodes:
                yield self._node_to_message(node)
            return

        raise ValueError(f"Unknown mode: {mode}")

    # ---------------------------- Search ---------------------------------

    def search_messages(
        self,
        query: str,
        *,
        regex: bool = False,
        case_sensitive: bool = False,
        author_display_in: Optional[Iterable[str]] = None,
        conv_ids_in: Optional[Iterable[Union[str, int]]] = None,
        mode: str = "current_path",
        created_between: Optional[Tuple[Optional[datetime], Optional[datetime]]] = None,
    ) -> List[Tuple[ConversationInfo, Message]]:
        """
        Search messages' textual content.

        Returns a list of (ConversationInfo, Message) where the message text matches the query.
        """

        if not query:
            return []

        conv_filter_ids: Optional[set] = None
        if conv_ids_in is not None:
            # Resolve any numeric indexes to IDs first
            conv_filter_ids = set()
            for ref in conv_ids_in:
                conv = self.get_conversation(ref)
                conv_filter_ids.add(str(conv.get("conversation_id") or conv.get("id") or conv.get("uuid") or ""))

        pattern: Optional[re.Pattern] = None
        q = query if case_sensitive else query.lower()

        if regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                pattern = re.compile(query, flags=flags)
            except re.error as e:
                raise ValueError(f"Invalid regex: {e}") from e

        results: List[Tuple[ConversationInfo, Message]] = []
        for info in self.list_conversations():
            if conv_filter_ids is not None and info.id not in conv_filter_ids:
                continue

            for msg in self.iter_messages(info.id, mode=mode):
                # Time window filter
                if created_between:
                    start, end = created_between
                    if start and (msg.create_time is None or msg.create_time < start):
                        continue
                    if end and (msg.create_time is None or msg.create_time > end):
                        continue

                # Author filter
                if author_display_in is not None:
                    if msg.author_display not in set(author_display_in):
                        continue

                text = msg.text_content()
                if not text:
                    continue

                if regex:
                    if not pattern.search(text):
                        continue
                else:
                    hay = text if case_sensitive else text.lower()
                    if q not in hay:
                        continue

                results.append((info, msg))

        return results

    # --------------------------- Assets ----------------------------------

    def resolve_asset(self, asset_pointer: str) -> Optional[str]:
        """Return the URL for a given asset pointer, if present in assets.json."""

        return self._assets_map.get(asset_pointer)

    # -------------------------- Convenience ------------------------------

    def __len__(self) -> int:
        return len(self._conversations)

    def conversations(self) -> List[Dict[str, Any]]:
        """Return raw conversation dicts. Prefer list_conversations for most use-cases."""

        return list(self._conversations)


# --------- Minimal CLI for quick inspection when running as a script ----------

def _print_dt(dt: Optional[datetime]) -> str:
    return dt.astimezone(timezone.utc).isoformat() if isinstance(dt, datetime) else "-"


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Inspect ChatGPT Data Export (data.json, assets.json)")
    p.add_argument("data", help="Path to data.json")
    p.add_argument("--assets", help="Path to assets.json", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub_list = sub.add_parser("list", help="List conversations")
    sub_list.add_argument("--limit", type=int, default=0, help="Limit output to N conversations")

    sub_show = sub.add_parser("show", help="Show messages for a conversation")
    sub_show.add_argument("conv", help="Conversation id, index, or title")
    sub_show.add_argument("--mode", choices=["current_path", "chronological_all"], default="current_path")

    sub_search = sub.add_parser("search", help="Search messages across conversations")
    sub_search.add_argument("query", help="Plain text or regex (with --regex)")
    sub_search.add_argument("--regex", action="store_true", help="Interpret query as a regular expression")
    sub_search.add_argument("--case-sensitive", action="store_true")
    sub_search.add_argument("--author", action="append", help="Filter to author display name (can repeat)")
    sub_search.add_argument("--mode", choices=["current_path", "chronological_all"], default="current_path")

    args = p.parse_args(argv)

    exp = ChatGPTExport.from_files(args.data, args.assets)

    # List mode...
    if args.cmd == "list":
        items = exp.list_conversations()
        if args.limit > 0:
            items = items[: args.limit]
        for i, info in enumerate(items):
            print(f"[{i}] {info.id} | {info.title} | created={_print_dt(info.create_time)} updated={_print_dt(info.update_time)}")
        return 0

    # Show mode...
    if args.cmd == "show":
        for msg in exp.iter_messages(args.conv, mode=args.mode):
            ctime = _print_dt(msg.create_time)
            print(f"{ctime} {msg.author_display}:")
            text = msg.text_content()
            if text:
                print(text)
            # Show any assets
            for part in msg.parts:
                if part.kind == "asset" and part.asset:
                    print(f"  [asset] {part.asset.content_type} -> {part.asset.asset_pointer} -> {part.asset.url or '-'}")
            print("-" * 40)
        return 0

    # Search mode...
    if args.cmd == "search":
        results = exp.search_messages(
            args.query,
            regex=args.regex,
            case_sensitive=args.case_sensitive,
            author_display_in=args.author,
            mode=args.mode,
        )
        for info, msg in results:
            print(f"{info.title} [{info.id}] { _print_dt(msg.create_time) } {msg.author_display}:")
            snippet = msg.text_content().strip().splitlines()[0] if msg.text_content() else ""
            print(f"  {snippet[:200]}")
        print(f"\nTotal: {len(results)}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
