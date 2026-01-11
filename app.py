#!/usr/bin/env python3
"""
app.py — Bluesky MTLD analyzer with background queue + Substack analyzer
"""
import hashlib
import html
import logging
import os
import queue
import re
import shelve
import subprocess
import sys
import threading
import datetime as dt
from urllib.parse import urlparse

import requests
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
REFRESH_SECONDS = int(os.environ.get("REFRESH_SECONDS", "10"))
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
<title>MTLD Results for Bluesky accounts</title>
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
<h1>MTLD Results for Bluesky accounts</h1>
<p>
  <form action="/mtld" method="get">
    <input type="text" name="handle" placeholder="jay.bsky.team" required>
    <button type="submit">Analyze</button>
  </form>
</p>
{status_box}
<table>
<tr><th>Handle</th><th>MTLD</th><th>Posts</th><th>Last Pull</th></tr>
{table_rows}
</table>
<p>MTLD (Measure of Textual Lexical Diversity) estimates vocabulary variety by counting on average how many words you string together before fewer than 72% of them are unique. The metric is relatively stable across passage lengths. Tokens are normalized to their lemma, so run/runs/running are all one verb, while runner is a separate noun. Proper nouns and anything out-of-vocabulary (usernames, misspellings) are skipped and do not affect the score. Lemmatization uses a 600 MB file and is CPU bound, so be patient.</p>
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
                meta_refresh = f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">'
                ahead = pos - 1
                if ahead > 0:
                    status_box = f'<div class="status-box queued">Queued: <strong>{job["handle"]}</strong> — {ahead} request{"s" if ahead != 1 else ""} ahead of you</div>'
                else:
                    status_box = f'<div class="status-box queued">Queued: <strong>{job["handle"]}</strong> — you\'re next</div>'
            elif job["status"] == "processing":
                meta_refresh = f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">'
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


## Substack analyzer ##

def resolve_substack_post_id(post_id):
    """Follow redirect from substack.com/home/post/p-{id} to get actual article URL."""
    url = f"https://substack.com/home/post/p-{post_id}"
    logger.info(f"Resolving post ID redirect: {url}")
    resp = requests.head(url, allow_redirects=False, timeout=10)
    if resp.status_code in (301, 302) and 'Location' in resp.headers:
        return resp.headers['Location']
    raise ValueError(f"Could not resolve post ID {post_id}")


def parse_substack_url(url):
    """Extract subdomain and slug from a Substack URL.

    Supported formats:
    - lucent.substack.com/p/article-slug
    - open.substack.com/pub/lucent/p/article-slug
    - substack.com/home/post/p-182523009 (follows redirect)
    - customdomain.com/p/article-slug
    """
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path.split('/')[0]
    path = parsed.path

    # Handle open.substack.com/pub/{subdomain}/p/{slug}
    if host == 'open.substack.com':
        match = re.search(r'/pub/([^/]+)/p/([^/]+)', path)
        if match:
            subdomain = match.group(1)
            slug = match.group(2)
            return subdomain, slug, f"{subdomain}.substack.com"
        raise ValueError(f"Could not parse open.substack.com URL: {url}")

    # Handle substack.com/home/post/p-{post_id} by following redirect
    if host in ('substack.com', 'www.substack.com'):
        match = re.search(r'/home/post/p-(\d+)', path)
        if match:
            redirect_url = resolve_substack_post_id(match.group(1))
            return parse_substack_url(redirect_url)  # Recurse with resolved URL
        raise ValueError(f"Could not parse substack.com URL: {url}")

    # Handle both lucent.substack.com and custom domains
    if '.substack.com' in host:
        subdomain = host.replace('.substack.com', '')
    else:
        # For custom domains, use the full host
        subdomain = host

    # Extract slug from path: /p/face-the-ick or /p/face-the-ick/
    match = re.search(r'/p/([^/]+)', path)
    if not match:
        raise ValueError(f"Could not extract article slug from URL: {url}")
    slug = match.group(1)

    return subdomain, slug, host


def fetch_substack_article(subdomain, slug, host):
    """Fetch article from Substack API."""
    # Try substack.com subdomain first, fall back to custom domain
    if '.substack.com' not in host:
        api_url = f"https://{subdomain}.substack.com/api/v1/posts/{slug}"
    else:
        api_url = f"https://{host}/api/v1/posts/{slug}"

    logger.info(f"Fetching Substack API: {api_url}")
    resp = requests.get(api_url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def strip_html(html_text):
    """Convert HTML to plain text."""
    # Remove script/style content
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    # Replace block elements with newlines
    text = re.sub(r'<(p|div|br|h[1-6]|li)[^>]*>', '\n', text, flags=re.IGNORECASE)
    # Remove remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode HTML entities
    text = html.unescape(text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


SUBSTACK_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<title>Lexical Diversity Analyzer</title>
<style>
  body {{ font-family: sans-serif; margin: 2em; max-width: 800px; }}
  h1 {{ font-size: 1.4em; }}
  .meta {{ color: #666; margin-bottom: 1.5em; }}
  .bar-container {{ margin: 1em 0; }}
  .bar-track {{ border-radius: 4px; height: 28px; position: relative; background: linear-gradient(90deg, #b91c1c, #fbbf24 50%, #15803d); }}
  .bar-mask {{ position: absolute; right: 0; top: 0; height: 100%; background: #e0e0e0; border-radius: 0 4px 4px 0; }}
  .bar-value {{ position: absolute; top: 50%; transform: translateY(-50%); color: white; font-weight: bold; font-size: 0.9em; text-shadow: 0 1px 2px rgba(0,0,0,0.5); }}
  .bar-label {{ display: flex; justify-content: space-between; font-size: 0.85em; color: #333; margin-top: 4px; }}
  .measure {{ margin: 1.5em 0; }}
  .measure-name {{ font-weight: bold; margin-bottom: 0.3em; }}
  .measure-desc {{ font-size: 0.9em; color: #555; margin-bottom: 0.5em; }}
  .stats {{ background: #f5f5f5; padding: 1em; border-radius: 4px; margin-top: 1.5em; }}
  .input-section {{ margin-bottom: 2em; padding-bottom: 1.5em; border-bottom: 1px solid #ddd; }}
  .input-section:last-of-type {{ border-bottom: none; }}
  .section-title {{ font-weight: bold; margin-bottom: 0.5em; color: #333; }}
  input[type="text"] {{ width: 100%; padding: 8px; box-sizing: border-box; }}
  textarea {{ width: 100%; padding: 8px; box-sizing: border-box; font-family: inherit; resize: vertical; }}
  button {{ padding: 8px 20px; margin-top: 0.5em; cursor: pointer; }}
  .error {{ background: #ffcccc; padding: 1em; border-radius: 4px; }}
</style>
</head>
<body>
<h1>Lexical Diversity Analyzer</h1>

<div class="input-section">
  <div class="section-title">Analyze a Substack article</div>
  <form action="/substack" method="get">
    <input type="text" name="url" placeholder="https://example.substack.com/p/article-slug" value="{url_value}">
    <button type="submit">Analyze URL</button>
  </form>
</div>

<div class="input-section">
  <div class="section-title">Or paste your own text</div>
  <form action="/substack" method="post">
    <textarea name="text" rows="12" placeholder="Paste your text here...">{text_value}</textarea>
    <button type="submit">Analyze Text</button>
  </form>
</div>

{content}
</body>
</html>"""


def bar_html(name, desc, value, low, high, low_label, high_label, invert=False, fmt=".2f"):
    """Generate a bar chart for a measure."""
    # Clamp and calculate percentage
    clamped = max(low, min(high, value))
    pct = ((clamped - low) / (high - low)) * 100
    if invert:
        pct = 100 - pct  # low values fill more (good on right)
    pct = max(5, pct)  # minimum visible width, no upper cap
    mask_pct = 100 - pct

    formatted = f"{value:{fmt}}"
    text_right = mask_pct + 2
    return f"""
    <div class="measure">
      <div class="measure-name">{name}: {formatted}</div>
      <div class="measure-desc">{desc}</div>
      <div class="bar-container">
        <div class="bar-track">
          <div class="bar-mask" style="width: {mask_pct:.1f}%"></div>
          <span class="bar-value" style="right: calc({text_right:.1f}% + 4px)">{formatted}</span>
        </div>
        <div class="bar-label"><span>{low_label}</span><span>{high_label}</span></div>
      </div>
    </div>"""


def build_ld_bars(ld_result):
    """Build the bar charts for lexical diversity metrics."""
    bars = []

    # MTLD: real essays range 43-130, median 77
    bars.append(bar_html(
        "MTLD",
        "How many words until you fall into a verbal rut? Speeches hammering the same slogans score low. Essayists exploring fresh terrain—philosophy, then history, then anecdote—score high.",
        ld_result.mtld, 40, 140, "Ruts quickly", "Stays fresh", fmt=".0f"
    ))

    # HD-D: real essays range 0.79-0.88, median 0.84
    bars.append(bar_html(
        "HD-D",
        "How much does each word choice surprise? Conversational filler like 'I think maybe we should think about' scores low. Dense prose where every word does work scores high.",
        ld_result.hdd, 0.78, 0.90, "Common words", "Precise words"
    ))

    # MATTR: real essays range 0.73-0.84, median 0.79
    bars.append(bar_html(
        "MATTR",
        "Do you stay sharp throughout or start strong and coast? Catches the difference between sustained craft and an inspired opening followed by a repetitive middle.",
        ld_result.mattr, 0.72, 0.86, "Uneven", "Consistent"
    ))

    # Maas: real essays range 0.035-0.054, median 0.045, LOWER is better
    bars.append(bar_html(
        "Maas",
        "Do you front-load your vocabulary or keep discovering new words? Technical writing that defines terms early and repeats them scores high. Exploratory writing that keeps evolving scores low.",
        ld_result.maas, 0.03, 0.06, "Exhausts early", "Keeps discovering", invert=True, fmt=".3f"
    ))

    return bars


def substack_results_html(article, ld_result):
    """Build results HTML for a Substack article."""
    title = article.get('title', 'Untitled')
    wordcount = article.get('wordcount', 0)
    bars = build_ld_bars(ld_result)

    content = f"""
    <h2>{html.escape(title)}</h2>
    <div class="meta">{wordcount} words → {ld_result.ntokens} tokens after preprocessing</div>
    {''.join(bars)}
    <div class="stats">
      <strong>Raw stats:</strong> {ld_result.ntypes} unique lemmas from {ld_result.ntokens} tokens
      (TTR: {ld_result.ttr:.3f})
    </div>
    """
    return content


def text_results_html(ld_result, word_count):
    """Build results HTML for pasted text."""
    bars = build_ld_bars(ld_result)

    content = f"""
    <h2>Pasted Text Analysis</h2>
    <div class="meta">~{word_count} words → {ld_result.ntokens} tokens after preprocessing</div>
    {''.join(bars)}
    <div class="stats">
      <strong>Raw stats:</strong> {ld_result.ntypes} unique lemmas from {ld_result.ntokens} tokens
      (TTR: {ld_result.ttr:.3f})
    </div>
    """
    return content


@app.route("/substack", methods=["GET", "POST"])
def substack_route():
    url = ""
    text = ""
    content = ""

    if request.method == "POST":
        # Handle pasted text
        text = request.form.get("text", "").strip()
        if not text:
            content = '<div class="error">Please paste some text to analyze.</div>'
        else:
            try:
                tokens = preprocess_text(text)
                if len(tokens) < 50:
                    raise ValueError(f"Too few tokens ({len(tokens)}) after preprocessing. Need at least 50.")

                ld_result = compute_lexdiv(tokens)
                word_count = len(text.split())
                content = text_results_html(ld_result, word_count)

            except ValueError as e:
                content = f'<div class="error">{e}</div>'
            except Exception as e:
                logger.exception("Text analysis failed")
                content = f'<div class="error">Error: {e}</div>'

    else:
        # Handle URL (GET request)
        url = request.args.get("url", "").strip()
        if not url:
            pass  # Show empty form
        else:
            try:
                subdomain, slug, host = parse_substack_url(url)
                article = fetch_substack_article(subdomain, slug, host)

                body_html = article.get('body_html', '')
                if not body_html:
                    raise ValueError("Article has no content")

                plain_text = strip_html(body_html)
                tokens = preprocess_text(plain_text)

                if len(tokens) < 50:
                    raise ValueError(f"Too few tokens ({len(tokens)}) after preprocessing. Need at least 50.")

                ld_result = compute_lexdiv(tokens)
                content = substack_results_html(article, ld_result)

            except requests.HTTPError as e:
                content = f'<div class="error">Failed to fetch article: {e}</div>'
            except ValueError as e:
                content = f'<div class="error">{e}</div>'
            except Exception as e:
                logger.exception("Substack analysis failed")
                content = f'<div class="error">Error: {e}</div>'

    return SUBSTACK_TEMPLATE.format(
        url_value=html.escape(url),
        text_value=html.escape(text),
        content=content
    )


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    app.run(host="0.0.0.0", port=port, threaded=True)
