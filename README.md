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
| `list_reads` | List books paginated (10 per page, compact: title, author, progress) |
| `list_all_reads` | Full reading history — all books in compact format |
| `get_read` | Get full details of a specific read (chapters, progress) |
| `get_read_content` | Get HTML text content of a read |
| `add_url` | Add URL for TTS reading |
| `add_document` | Upload epub/pdf file |
| `add_directory` | Upload all books from a directory (background, with retry) |
| `upload_status` | Check background upload progress |
| `delete_read` | Remove from library |
| `deduplicate` | Find and remove duplicate reads (keeps oldest) |
| `mark_almost_finished` | Mark books at 97%+ progress as finished |
| `list_voices` | Available TTS voices |
| `get_voice` | Voice details |
| `get_config` | User settings (voice, speed, font) |
| `update_config` | Change default voice/speed |
| `get_customer` | Subscription info & credits |
| `get_collections` | User collections |
| `get_bookmarks` | Bookmarks for a read |
| `update_progress` | Update listening position |

## Architecture

- **Auth**: Firebase refresh token → short-lived access token (auto-refreshed, thread-safe)
- **Data source**: `/v1/reader/collections/books` endpoint (full history, 345+ books)
- **Caching**: 60s TTL on book list, invalidated on mutations (add/delete)
- **Upload queue**: Background thread with retry (3 attempts), rate limiting, pause for priority uploads
- **Thread safety**: Locks on token cache and reads cache

## Requirements

- Python ≥ 3.11
- Dependencies: httpx, mcp

## License

MIT
