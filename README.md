# mcp-elevenreader

> **Listen to any document from Claude or Cursor** — upload epubs/pdfs, manage TTS reading queue and control playback via ElevenLabs ElevenReader.

MCP server for [ElevenReader](https://elevenreader.io) — ElevenLabs text-to-speech reader.

## Quick Start

```bash
# 1. Get refresh token: ElevenReader → F12 Console → copy stsTokenManager.refreshToken
# 2. Run via Claude Code (or add to Claude Desktop config below)
claude mcp add elevenreader -e ELEVEN_REFRESH_TOKEN=your-token -- uvx mcp-elevenreader
# 3. Ask Claude: "List my ElevenReader books"
```

> Works with Claude Code, Claude Desktop, Cursor, Kiro and opencode — see Setup below for JSON configs.

## Setup

### 1. Get refresh token

Open https://elevenreader.io, log in, then run in browser console (F12 → Console):

```javascript
JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k => k.startsWith('firebase:authUser:')))).stsTokenManager.refreshToken
```

The refresh token is long-lived (months). Access tokens are refreshed automatically.

### 2. Connect to Claude Code

```bash
claude mcp add elevenreader -e ELEVEN_REFRESH_TOKEN=your-token -- uvx mcp-elevenreader
```

To make it available in all projects, add to `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "elevenreader": {
      "command": "uvx",
      "args": ["mcp-elevenreader"],
      "env": {
        "ELEVEN_REFRESH_TOKEN": "your-token"
      }
    }
  }
}
```

### Other clients (Claude Desktop / Kiro / Cursor)

```json
{
  "mcpServers": {
    "elevenreader": {
      "command": "uvx",
      "args": ["mcp-elevenreader"],
      "env": {
        "ELEVEN_REFRESH_TOKEN": "your-token"
      }
    }
  }
}
```

### opencode

Add to `~/.config/opencode/opencode.json`. Note: opencode uses **`environment`** (not `env`) for MCP server env vars:

```json
{
  "mcp": {
    "elevenreader": {
      "type": "local",
      "enabled": true,
      "command": ["uvx", "mcp-elevenreader"],
      "environment": {
        "ELEVEN_REFRESH_TOKEN": "your-token"
      }
    }
  }
}
```

Config is only read at opencode startup — **quit and restart** opencode after adding. If the token still isn't picked up, check it's under `environment`, not `env`.

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

## Development

```bash
git clone https://github.com/MIt9/mcp-elevenreader
cd mcp-elevenreader
uv sync
mcp dev src/mcp_elevenreader/server.py
```

## Requirements

- Python ≥ 3.10
- Dependencies: httpx, mcp

## License

MIT
