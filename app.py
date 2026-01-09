#!/usr/bin/env python3
"""
app.py — Bluesky MTLD analyzer with background queue
"""
import hashlib
import logging
import os
import queue
import shelve
import subprocess
import sys
import threading
import datetime as dt
from flask import Flask, redirect, request, url_for

from my_ld import preprocess_text, compute_lexdiv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

CACHE_PATH = os.environ.get("CACHE_PATH", "./data/mtld_cache")
POST_LIMIT = 500
ACCOUNT_DUMPS_DIR = "./account_dumps"

app = Flask(__name__, static_folder="static")

# Job queue and state
_queue = queue.Queue()
_jobs = {}  # job_id -> {"status": "queued"|"processing"|"done"|"error", "handle": str, "error": str|None, "position": int}
_jobs_lock = threading.RLock()  # Use RLock to allow reentrant locking
_cache_lock = threading.Lock()  # Lock for cache access


def now_iso():
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def job_id_for(handle):
    return hashlib.sha256(f"{handle}:{now_iso()}".encode()).hexdigest()[:12]


def open_cache():
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    return shelve.open(CACHE_PATH, writeback=False)


def read_cache():
    """Thread-safe cache read that returns a dict copy"""
    with _cache_lock:
        with open_cache() as cache:
            return dict(cache)


def write_cache(handle, entry):
    """Thread-safe cache write"""
    with _cache_lock:
        with open_cache() as cache:
            cache[handle] = entry


def fetch_with_bash(handle, limit):
    script = os.path.abspath("fetch_repo.sh")
    logger.info(f"Executing fetch_repo.sh for {handle}")
    try:
        result = subprocess.run(
            ["bash", script, handle, str(limit)],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(f"fetch_repo.sh completed for {handle}")
        return f"{ACCOUNT_DUMPS_DIR}/{handle}.txt"
    except subprocess.CalledProcessError as e:
        # Parse error message from the script
        error_output = (e.stderr + e.stdout).strip()

        # Look for our custom error messages
        if "ERROR:" in error_output:
            # Extract the error message after "ERROR:"
            error_lines = [line for line in error_output.split('\n') if 'ERROR:' in line]
            if error_lines:
                error_msg = error_lines[-1].split('ERROR:')[-1].strip()
                raise ValueError(error_msg)

        # Fallback for unexpected errors
        raise ValueError(f"Failed to fetch posts for {handle}")


def get_queue_position(job_id):
    with _jobs_lock:
        queued = [jid for jid, j in _jobs.items() if j["status"] == "queued"]
        if job_id in queued:
            return queued.index(job_id) + 1
    return 0


def update_positions():
    with _jobs_lock:
        queued = [jid for jid, j in _jobs.items() if j["status"] == "queued"]
        for i, jid in enumerate(queued):
            _jobs[jid]["position"] = i + 1


def worker():
    logger.info("Worker thread started")
    while True:
        job_id, handle = _queue.get()
        logger.info(f"Processing job {job_id} for handle: {handle}")

        with _jobs_lock:
            _jobs[job_id]["status"] = "processing"
            update_positions()

        try:
            logger.info(f"Fetching posts for {handle} (limit: {POST_LIMIT})")
            textfile = fetch_with_bash(handle, POST_LIMIT)

            logger.info(f"Reading text file: {textfile}")
            text = open(textfile, "r", encoding="utf-8").read()

            logger.info(f"Preprocessing text for {handle}")
            tokens = preprocess_text(text)

            logger.info(f"Computing lexical diversity for {handle}")
            mtld = compute_lexdiv(tokens).mtld

            entry = {
                "handle": handle,
                "date": now_iso(),
                "posts": POST_LIMIT,
                "mtld": mtld,
            }
            write_cache(handle, entry)

            with _jobs_lock:
                _jobs[job_id]["status"] = "done"

            logger.info(f"Job {job_id} completed successfully. MTLD: {mtld:.1f}")

        except Exception as e:
            logger.error(f"Job {job_id} failed with error: {e}", exc_info=True)
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(e)

        _queue.task_done()


# Start single background worker
_worker_thread = threading.Thread(target=worker, daemon=True)
_worker_thread.start()


def build_table_rows(cache, highlight=None):
    entries = sorted(cache.values(), key=lambda x: x["mtld"], reverse=True)
    if not entries:
        return "<tr><td colspan='4' class='empty'>No handles analyzed yet.</td></tr>"
    rows = []
    for e in entries:
        date = e["date"].split("T")[0]
        link = f"https://bsky.app/profile/{e['handle']}"
        hl = " class='highlight'" if e["handle"] == highlight else ""
        rows.append(
            f"<tr{hl}><td><a href='{link}'>{e['handle']}</a></td>"
            f"<td>{e['mtld']:.1f}</td>"
            f"<td>{e['posts']}</td>"
            f"<td>{date}</td></tr>"
        )
    return "\n".join(rows)


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<title>MTLD Results</title>
{meta_refresh}
<style>
  body {{ font-family: sans-serif; margin: 2em; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
  th {{ background: #eee; }}
  .empty {{ font-style: italic; color: #555; }}
  .highlight {{ background: #ffffcc; }}
  .status-box {{ padding: 1em; margin: 1em 0; border-radius: 4px; }}
  .queued {{ background: #e0e0e0; }}
  .processing {{ background: #fff3cd; }}
  .error {{ background: #ffcccc; }}
</style>
</head>
<body>
<h1>MTLD Results</h1>
<p>
  <form action="/mtld" method="get">
    <input type="text" name="handle" placeholder="lucent.social" required>
    <button type="submit">Analyze</button>
  </form>
</p>
{status_box}
<table>
<tr><th>Handle</th><th>MTLD</th><th>Posts</th><th>Last Pull</th></tr>
{table_rows}
</table>
<p>MTLD (Measure of Textual Lexical Diversity) estimates vocabulary variety by counting on average how many words you string together before fewer than 72% of them are unique. The metric is relatively stable across passage lengths. Tokens are normalized to their lemma, so run/runs/running are all one verb, while runner is a separate noun. Proper nouns and anything out-of-vocabulary (usernames, misspellings) are skipped and do not affect the score.</p>
</body>
</html>"""


def build_html(cache, job_id=None, highlight=None):
    meta_refresh = ""
    status_box = ""

    if job_id:
        with _jobs_lock:
            job = _jobs.get(job_id)

        if job:
            if job["status"] == "queued":
                pos = get_queue_position(job_id)
                meta_refresh = '<meta http-equiv="refresh" content="2">'
                ahead = pos - 1
                if ahead > 0:
                    status_box = f'<div class="status-box queued">Queued: <strong>{job["handle"]}</strong> — {ahead} request{"s" if ahead != 1 else ""} ahead of you</div>'
                else:
                    status_box = f'<div class="status-box queued">Queued: <strong>{job["handle"]}</strong> — you\'re next</div>'
            elif job["status"] == "processing":
                meta_refresh = '<meta http-equiv="refresh" content="2">'
                status_box = f'<div class="status-box processing">Processing <strong>{job["handle"]}</strong>...</div>'
            elif job["status"] == "error":
                status_box = f'<div class="status-box error">Error processing {job["handle"]}: {job["error"]}</div>'
            elif job["status"] == "done":
                highlight = job["handle"]

    rows = build_table_rows(cache, highlight)
    return HTML_TEMPLATE.format(
        meta_refresh=meta_refresh,
        status_box=status_box,
        table_rows=rows,
    )


@app.route("/")
def index():
    job_id = request.args.get("job")
    hl = request.args.get("hl")
    cache = read_cache()
    return build_html(cache, job_id=job_id, highlight=hl)


@app.route("/mtld", methods=["GET"])
def mtld_route():
    handle = request.args.get("handle")
    assert handle, "handle required"

    logger.info(f"Account requested: {handle}")

    cache = read_cache()
    if handle in cache:
        logger.info(f"Account {handle} found in cache")
        return redirect(url_for("index", hl=handle))

    job_id = job_id_for(handle)
    with _jobs_lock:
        _jobs[job_id] = {"status": "queued", "handle": handle, "error": None, "position": _queue.qsize() + 1}

    _queue.put((job_id, handle))
    logger.info(f"Job {job_id} queued for handle: {handle}")

    return redirect(url_for("index", job=job_id))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    app.run(host="0.0.0.0", port=port, threaded=True)
