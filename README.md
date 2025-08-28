# chatgpt_export
Toolset to help interact with your ChatGPT chat history

Clone the chatgpt_export toolset git repository somewhere.

Obtain your ChatGPT data:

- Log into ChatGPT
- Click on your profile picture (bottom-left of the ChatGPT window on a desktop browser)
- Click "Settings"
- Click "Data controls"
- Click the "Export" button next to "Export data"
- Click "Confirm export" on the "Are you sure?" pop-up

Eventually, you will receive an email from ChatGPT containing a download link for your export data.

Download the export data (which will be a potentially large zip file).

Locate the "chat.html" file within the zip file and copy it into the chatgpt_export (clone) folder.

Run the "chat_export_to_json.py" tool to generate the "data.json" and "assets.json" files from the "chat.html" file:

  $ python chat_export_to_json.py chat.html

You can now use the "chatgpt_export.py" command line tool to do the following:

1. List your chats
2. Output the messages from a specific chat
3. Search for some text in all of your chats

Or, if you prefer to interact with your chat history programmatically, you should look at the "export-test.py" example program to see how you can enumerate chats, enumerate messages in a specific chat, and search for text within your chats.

This toolset is licensed under the Apache 2.0 Open Source licence.
