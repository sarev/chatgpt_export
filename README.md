# chatgpt_export
Toolset to extract and work with your ChatGPT chat history.

## Contents
- `chat_export_to_json.py` — streaming extractor that pulls `jsonData` and `assetsJson` out of `chat.html` into `data.json` and `assets.json`.
- `chatgpt_export.py` — library and CLI to list conversations, enumerate messages, and search text.
- `export_test.py` — minimal example of programmatic use.

## Requirements
- Python 3.9+ (uses modern typing and dataclasses).
- No third-party dependencies.

## 1. Get your ChatGPT export
1. Log into ChatGPT.
2. Click your profile picture (bottom-left on desktop).
3. Settings → Data controls.
4. Click **Export** next to **Export data**.
5. Click **Confirm export**.
6. Wait for the email, then download the ZIP.

Inside the ZIP you will find a `chat.html` that contains your full message graph and any asset pointers.

## 2. Extract `data.json` and `assets.json`
Copy `chat.html` into the cloned repository folder, then run:

```bash
python chat_export_to_json.py chat.html
```

By default this writes `data.json` and `assets.json` next to `chat.html`.

Options:

```bash
python chat_export_to_json.py /path/to/chat.html   --data-out /somewhere/data.json   --assets-out /somewhere/assets.json   --overwrite   --chunk-size 1048576   --trailing-buffer 8192
```

Notes:
- The extractor is streaming and safe for very large one-line JSON values (hundreds of MiB). It never loads the entire line into memory.
- It trims everything up to and including the `=` after the variable name and removes the trailing `;` (and any trailing spaces or `\r`).
- It recognises `var|let|const`, an optional `window.` prefix, and the variable names `jsonData` and `assetsJson`.
- If the HTML has no final newline the extractor still trims correctly.
- If either variable is not found you will see a message such as `jsonData not found.`

## 3. CLI usage for exploring your history
The `chatgpt_export.py` module includes a CLI. Pass `data.json` (and optionally `--assets assets.json`) followed by a command.

### List conversations
```bash
python chatgpt_export.py data.json --assets assets.json list --limit 10
```
Output format:
```
[0] <conversation_id> | <title> | created=<UTC> updated=<UTC>
```

### Show messages in a conversation
You can address a conversation by id, index, or exact title.

```bash
# By index from the list command:
python chatgpt_export.py data.json --assets assets.json show 0

# By id or title:
python chatgpt_export.py data.json --assets assets.json show "abcd-ef01-..."
python chatgpt_export.py data.json --assets assets.json show "How to do X"
```

Modes:
- `--mode current_path` (default) follows the same linear “current path” as the HTML viewer. This walks `current_node → parent` to the root and shows only text or multimodal text nodes that the HTML would display.
- `--mode chronological_all` includes every mapping node that has message parts, sorted by `create_time` then id.

### Search across conversations
```bash
# Case-insensitive plain text search
python chatgpt_export.py data.json --assets assets.json search "vector database"

# Regular expression
python chatgpt_export.py data.json --assets assets.json search "(?i)\bvector\b" --regex
```

You will see matching messages with conversation title, timestamp, author, and a short snippet.

## 4. Programmatic usage
```python
from chatgpt_export import ChatGPTExport
from datetime import datetime, timezone

exp = ChatGPTExport.from_files("data.json", "assets.json")

# List all chats with indices
for idx, info in enumerate(exp.list_conversations()):
    print(f"[{idx}] {info.id} | {info.title} | {info.create_time}")

# Enumerate messages on the HTML "current path"
for msg in exp.iter_messages(0, mode="current_path"):   # 0 is the index from the list
    print(msg.create_time, msg.author_display)
    print(msg.text_content())
    for part in msg.parts:
        if part.kind == "asset":
            print("asset:", part.asset.content_type, "->", part.asset.url)

# Search with a time window and author filter
start = datetime(2024, 1, 1, tzinfo=timezone.utc)
end   = datetime(2025, 1, 1, tzinfo=timezone.utc)

results = exp.search_messages(
    "benchmark",
    regex=False,
    author_display_in=["ChatGPT"],       # filter by display name
    created_between=(start, end),
    mode="current_path",
)
print(f"Matches: {len(results)}")
```

## Behaviour and assumptions
- **Timestamps** are parsed from either UNIX seconds or ISO 8601 and exposed as timezone-aware UTC `datetime` instances. Missing values are `None`.
- **Authors**: `"assistant"` and `"tool"` are normalised to `ChatGPT`. `"system"` is hidden unless `metadata.is_user_system_message` is true, in which case it is shown as `Custom user info`. This mirrors the export HTML I've looked at.
- **Assets**: `assets.json` is treated as a mapping from asset pointer to a URL. Missing pointers yield `None`.

## Performance and limits
- The extractor uses a byte stream with a small trailing buffer (default 8192 bytes) to strip the final semicolon and whitespace. Increase `--trailing-buffer` if you encounter pathological amounts of trailing whitespace.
- Reading is chunked (default 1 MiB). Adjust `--chunk-size` to trade throughput for memory.
- `assets.json` may be absent in older exports. The tools still work, but asset URLs will be `None`.

## Troubleshooting
- **`jsonData not found` or `assetsJson not found`**: Ensure the file is the unmodified `chat.html` from the ZIP. Some browsers prettify HTML on save which can change formatting. The extractor expects single-line assignments for each variable.
- **`Refusing to overwrite`**: Pass `--overwrite` if you want to replace existing outputs.
- **`Conversation not found`** when using the CLI `show` command: If you pass a title, it must match exactly. Try using the index or id from the `list` output.

## Security and privacy
- If you are using ChatGPT in a work context, check with your IT team/manager before exporting your ChatGPT data. 
- Your data stays on your machine. No network calls are made. However, you need to download the export itself from ChatGPT's servers. 
- The export can be very large. Store it on an encrypted disk if you have sensitive content.

## Licence
This toolset is licensed under the Apache 2.0 open source licence.
