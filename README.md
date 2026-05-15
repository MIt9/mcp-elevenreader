# mcp-elevenreader

MCP server for [ElevenReader](https://elevenreader.io) — ElevenLabs text-to-speech reader.

## Setup

### 1. Get refresh token

Open https://elevenreader.io, log in, then run in browser console (F12 → Console):

```javascript
JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k => k.startsWith('firebase:authUser:')))).stsTokenManager.refreshToken
```

### 2. Configure MCP

Add to your MCP config (`~/.kiro/settings.json`, Claude Desktop, etc.):

```json
{
  "mcpServers": {
    "elevenreader": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-elevenreader", "python", "server.py"],
      "env": {
        "ELEVEN_REFRESH_TOKEN": "paste-your-refresh-token-here"
      }
    }
  }
}
```

The refresh token is long-lived (months). Access tokens are refreshed automatically.

## Tools

| Tool | Description |
|------|-------------|
| `list_reads` | List all documents/books in library |
| `get_read` | Get read details (chapters, progress) |
| `get_read_content` | Get HTML text content |
| `add_url` | Add URL for TTS reading |
| `add_document` | Upload epub/pdf file |
| `add_directory` | Upload all books from a directory (background, with retry) |
| `upload_status` | Check background upload progress |
| `delete_read` | Remove from library |
| `deduplicate` | Find and remove duplicate reads (keeps oldest) |
| `list_voices` | Available voices |
| `get_voice` | Voice details |
| `get_config` | User settings |
| `update_config` | Change voice/speed |
| `get_customer` | Subscription & credits |
| `get_collections` | User collections |
| `get_bookmarks` | Bookmarks for a read |
| `update_progress` | Update listening position |
