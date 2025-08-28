#!/usr/bin/env python3
#
# Example use cases for the 'chatgpt_export' module.
#
# Copyright (c) 2025, 7th software Ltd.
# All rights reserved.

from chatgpt_export import ChatGPTExport

exp = ChatGPTExport.from_files("data.json", "assets.json")

# 1) List all chats
for idx, info in enumerate(exp.list_conversations()):
    print(f"[{idx}] {info.id} | {info.title} | {info.create_time}")
    # print(f"[{idx}] {info.id} | {info.title.strip()} | {info.create_time}")

# 2) Show messages in a chat (by id, index, or exact title)
print("")
for msg in exp.iter_messages(8, mode="current_path"):
    print(msg.create_time, msg.author_display)
    print(msg.text_content())
    for part in msg.parts:
        if part.kind == "asset":
            print("asset:", part.asset.content_type, part.asset.asset_pointer, "->", part.asset.url)
    print("")

# 3) Search for text across all chats
print("\nSearch results...\n")
hits = exp.search_messages("gaussian", regex=False)
for conv, msg in hits:
    print(f"{conv.title} - {msg.create_time} - {msg.author_display}:")
    print(f"  {msg.text_content().splitlines()[0]}")
