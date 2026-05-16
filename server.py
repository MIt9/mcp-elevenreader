import os
import json
import time
import threading
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("elevenreader")

BASE_URL = "https://api.elevenlabs.io"
FIREBASE_KEY = "AIzaSyDSJy4Xs8dz8NNlAImw1CKWbWl23JTf-F0"
STATE_FILE = Path(__file__).parent / ".upload_state.json"
UPLOAD_DELAY = 3  # seconds between uploads
MAX_RETRIES = 3

_token_cache = {"access_token": None, "expires_at": 0}
_token_lock = threading.Lock()
_upload_thread: threading.Thread | None = None
_upload_pause = threading.Event()
_upload_pause.set()  # not paused initially


# --- Auth ---

def _get_access_token() -> str:
    refresh_token = os.environ.get("ELEVEN_REFRESH_TOKEN")
    if not refresh_token:
        raise RuntimeError("ELEVEN_REFRESH_TOKEN env var is not set")

    with _token_lock:
        if _token_cache["access_token"] and _token_cache["expires_at"] > time.time() + 60:
            return _token_cache["access_token"]

        r = httpx.post(
            f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_KEY}",
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        r.raise_for_status()
        resp = r.json()

        _token_cache["access_token"] = resp["id_token"]
        _token_cache["expires_at"] = time.time() + int(resp["expires_in"])
        return _token_cache["access_token"]


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {_get_access_token()}"},
        timeout=60,
    )


def _encode_read_id(read_id: str) -> str:
    return read_id.replace(":", "%3A")


# --- Upload queue ---

def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def _upload_worker():
    state = _load_state()
    if state.get("status") != "running":
        return

    pending = state.get("pending", [])
    while pending and state.get("status") == "running":
        _upload_pause.wait()  # block if paused by priority upload
        file_path = pending[0]

        success = False
        for attempt in range(MAX_RETRIES):
            try:
                with _client() as c:
                    with open(file_path, "rb") as f:
                        r = c.post(
                            "/v1/reader/reads/add/v2",
                            files={"from_document": (Path(file_path).name, f)},
                        )
                        if r.status_code == 429:
                            wait = UPLOAD_DELAY * (attempt + 2)
                            time.sleep(wait)
                            continue
                        r.raise_for_status()
                        data = r.json()
                        state.setdefault("uploaded", []).append(
                            {"file": Path(file_path).name, "read_id": data["read_id"]}
                        )
                        success = True
                        break
            except Exception as e:
                if attempt == MAX_RETRIES - 1:
                    state.setdefault("failed", []).append(
                        {"file": Path(file_path).name, "error": str(e)}
                    )

        pending.pop(0)
        state["pending"] = pending
        state["progress"] = f"{len(state.get('uploaded', [])) + len(state.get('failed', []))}/{state['total']}"
        _save_state(state)
        time.sleep(UPLOAD_DELAY)

    state["status"] = "done"
    _save_state(state)


# --- Tools ---

@mcp.tool()
def add_directory(dir_path: str, extensions: str = ".epub,.pdf") -> str:
    """Upload all books from a directory (and subdirectories). Files are sorted by name so parts (ч1, ч2) stay together.

    Args:
        dir_path: Path to directory with books
        extensions: Comma-separated file extensions to upload (default: .epub,.pdf)
    """
    global _upload_thread

    # Check if already running
    if _upload_thread and _upload_thread.is_alive():
        return "Upload already in progress. Use upload_status to check progress."

    exts = [e.strip() for e in extensions.split(",")]
    root = Path(dir_path)
    files = sorted(
        str(f) for f in root.rglob("*") if f.suffix.lower() in exts and not f.name.startswith(".")
    )

    # Deduplicate: skip files already in library
    existing_titles = {read["title"] for read in _fetch_all_reads()}
    files = [f for f in files if Path(f).stem not in existing_titles and Path(f).name not in existing_titles]

    if not files:
        return "All files already uploaded."

    state = {
        "status": "running",
        "dir": dir_path,
        "total": len(files),
        "progress": f"0/{len(files)}",
        "pending": files,
        "uploaded": [],
        "failed": [],
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_state(state)

    _upload_thread = threading.Thread(target=_upload_worker, daemon=True)
    _upload_thread.start()

    return f"Started uploading {len(files)} files from {dir_path}. Use upload_status to check progress."


@mcp.tool()
def upload_status() -> dict:
    """Check the status of a background directory upload."""
    state = _load_state()
    if not state:
        return {"status": "no upload in progress"}
    return {
        "status": state.get("status"),
        "progress": state.get("progress"),
        "total": state.get("total"),
        "uploaded": len(state.get("uploaded", [])),
        "failed": len(state.get("failed", [])),
        "pending": len(state.get("pending", [])),
        "last_uploaded": state.get("uploaded", [])[-3:] if state.get("uploaded") else [],
        "last_failed": state.get("failed", [])[-3:] if state.get("failed") else [],
    }


def _compact_read(read: dict) -> dict:
    """Extract only essential fields from a read."""
    char_count = read.get("char_count", 0)
    offset = read.get("last_listened_char_offset", 0)
    progress = round(offset / char_count * 100) if char_count else 0
    return {
        "read_id": read["read_id"],
        "title": read.get("title", ""),
        "author": read.get("author") or "",
        "language": read.get("language", ""),
        "progress": f"{progress}%",
        "finished": bool(read.get("completed_at_unix") or progress >= 100),
        "word_count": read.get("word_count", 0),
        "added_at": read.get("added_at_unix", 0),
    }


_reads_cache = {"data": None, "expires_at": 0}
_reads_lock = threading.Lock()
CACHE_TTL = 60  # seconds


def _invalidate_cache():
    """Invalidate reads cache after mutations."""
    with _reads_lock:
        _reads_cache["data"] = None
        _reads_cache["expires_at"] = 0


def _fetch_all_reads() -> list[dict]:
    """Fetch all reads from API using collections/books (full history). Cached for 60s."""
    with _reads_lock:
        if _reads_cache["data"] and _reads_cache["expires_at"] > time.time():
            return _reads_cache["data"]
    all_reads = []
    cursor = None
    with _client() as c:
        while True:
            params = {"page_size": 500}
            if cursor:
                params["next_cursor"] = cursor
            r = c.get("/v1/reader/collections/books", params=params)
            r.raise_for_status()
            data = r.json()
            all_reads.extend(data.get("items", []))
            if not data.get("has_more") or not data.get("next_cursor"):
                break
            cursor = data["next_cursor"]
    with _reads_lock:
        _reads_cache["data"] = all_reads
        _reads_cache["expires_at"] = time.time() + CACHE_TTL
    return all_reads


@mcp.tool()
def list_reads(page_size: int = 10, page: int = 1) -> dict:
    """List documents/books in the library (paginated, compact).

    Args:
        page_size: Number of books per page (default: 10)
        page: Page number starting from 1 (default: 1)
    """
    all_reads = _fetch_all_reads()
    total = len(all_reads)
    start = (page - 1) * page_size
    end = start + page_size
    page_reads = [_compact_read(r) for r in all_reads[start:end]]
    return {
        "reads": page_reads,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
    }


@mcp.tool()
def list_all_reads() -> dict:
    """Get full reading history — all books in compact format (title, author, progress, language)."""
    all_reads = _fetch_all_reads()
    return {
        "total": len(all_reads),
        "reads": [_compact_read(r) for r in all_reads],
    }


@mcp.tool()
def get_read(read_id: str) -> dict:
    """Get details of a specific read (book/document)."""
    with _client() as c:
        r = c.get(f"/v1/reader/reads/{_encode_read_id(read_id)}")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_read_content(read_id: str) -> str:
    """Get HTML content of a read for viewing."""
    with _client() as c:
        r = c.get(
            f"/v1/reader/reads/{_encode_read_id(read_id)}/simple-html",
            params={"make_pageable": "false"},
        )
        r.raise_for_status()
        return r.text


@mcp.tool()
def add_url(url: str) -> dict:
    """Add a URL to the library for text-to-speech reading."""
    _upload_pause.clear()
    try:
        with _client() as c:
            r = c.post("/v1/reader/reads/add/v2", data={"from_url": url})
            r.raise_for_status()
            _invalidate_cache()
            return r.json()
    finally:
        _upload_pause.set()


@mcp.tool()
def add_document(file_path: str) -> dict:
    """Upload a document (epub, pdf) to the library."""
    _upload_pause.clear()
    try:
        with _client() as c:
            with open(file_path, "rb") as f:
                r = c.post(
                    "/v1/reader/reads/add/v2",
                    files={"from_document": (os.path.basename(file_path), f)},
                )
                r.raise_for_status()
                _invalidate_cache()
                return r.json()
    finally:
        _upload_pause.set()


@mcp.tool()
def delete_read(read_id: str) -> dict:
    """Delete a read from the library."""
    with _client() as c:
        r = c.delete(f"/v1/reader/reads/{_encode_read_id(read_id)}")
        r.raise_for_status()
        _invalidate_cache()
        return r.json()


@mcp.tool()
def deduplicate() -> dict:
    """Find and remove duplicate reads (same title). Keeps the oldest one."""
    reads = _fetch_all_reads()

    # Group by title
    by_title: dict[str, list] = {}
    for read in reads:
        title = read.get("title", "")
        by_title.setdefault(title, []).append(read)

    deleted = []
    for title, copies in by_title.items():
        if len(copies) <= 1:
            continue
        # Keep oldest (smallest created_at_unix), delete rest
        copies.sort(key=lambda x: x["created_at_unix"])
        for dup in copies[1:]:
            with _client() as c:
                c.delete(f"/v1/reader/reads/{_encode_read_id(dup['read_id'])}")
            deleted.append({"title": title, "read_id": dup["read_id"]})
            time.sleep(0.5)

    if deleted:
        _invalidate_cache()
    return {"deleted": len(deleted), "items": deleted}


@mcp.tool()
def list_voices() -> dict:
    """List available voices for reading."""
    with _client() as c:
        r = c.get("/v1/reader/voices")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_voice(voice_id: str) -> dict:
    """Get details of a specific voice."""
    with _client() as c:
        r = c.get(f"/v1/reader/voices/{voice_id}")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_config() -> dict:
    """Get user config (default voice, speed, font size, etc.)."""
    with _client() as c:
        r = c.get("/v1/reader/user_config")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def update_config(
    default_voice_id: str | None = None,
    playback_speed_rate: float | None = None,
) -> dict:
    """Update user config (voice, playback speed)."""
    body = {}
    if default_voice_id:
        body["default_voice_id"] = default_voice_id
    if playback_speed_rate:
        body["playback_speed_rate"] = playback_speed_rate
    with _client() as c:
        r = c.post("/v1/reader/user_config", json=body)
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_customer() -> dict:
    """Get subscription info: plan, credits, billing."""
    with _client() as c:
        r = c.get("/v1/reader/customer")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_collections() -> dict:
    """List user collections."""
    with _client() as c:
        r = c.get("/v1/reader/collections")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_bookmarks(read_id: str) -> list:
    """Get bookmarks for a specific read."""
    with _client() as c:
        r = c.get(f"/v1/reader/bookmarks/{_encode_read_id(read_id)}")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def update_progress(read_id: str, char_offset: int) -> dict:
    """Update listening progress for a read."""
    with _client() as c:
        r = c.patch(
            f"/v1/reader/reads/{_encode_read_id(read_id)}",
            json={"last_listened_char_offset": char_offset},
        )
        r.raise_for_status()
        return r.json()


@mcp.tool()
def mark_almost_finished(threshold: float = 0.97) -> dict:
    """Find books at 97-99% progress (not yet marked completed) and mark them as finished by setting offset to char_count.

    Args:
        threshold: Minimum progress ratio to consider as "almost finished" (default: 0.97)
    """
    reads = _fetch_all_reads()

    marked = []
    for read in reads:
        char_count = read.get("char_count", 0)
        offset = read.get("last_listened_char_offset", 0)
        if not char_count or read.get("completed_at_unix"):
            continue
        progress = offset / char_count
        if progress >= threshold and progress < 1.0:
            with _client() as c:
                r = c.patch(
                    f"/v1/reader/reads/{_encode_read_id(read['read_id'])}",
                    json={"last_listened_char_offset": char_count},
                )
                r.raise_for_status()
            marked.append({"title": read["title"], "progress": f"{progress:.1%}"})
            time.sleep(0.5)

    if marked:
        _invalidate_cache()
    return {"marked_completed": len(marked), "items": marked}


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
