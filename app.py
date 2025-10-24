# app.py
import os, sys, json, subprocess, datetime as dt
from flask import Flask, redirect, url_for, request
from my_ld import preprocess_text, compute_mtld

CACHE_PATH = "mtld_cache.json"
HTML_PATH = "static/index.html"
POST_LIMIT = 500
ACCOUNT_DUMPS_DIR = "./account_dumps"

app = Flask(__name__, static_folder="static")

def now_iso():
	return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

def load_cache(path=CACHE_PATH):
	return json.load(open(path, "r", encoding="utf-8"))

def save_cache(cache, path=CACHE_PATH):
	with open(path, "w", encoding="utf-8") as f:
		json.dump(cache, f, indent=None, ensure_ascii=False)

def fetch_with_bash(handle: str, limit: int) -> str:
	script = os.path.abspath("fetch_repo.sh")
	subprocess.check_call(["bash", script, handle, str(limit)])
	return f"{ACCOUNT_DUMPS_DIR}/{handle}.txt"

def build_html(cache):
	os.makedirs(os.path.dirname(HTML_PATH), exist_ok=True)
	entries = sorted(cache.values(), key=lambda x: x["mtld"], reverse=True)
	rows = []
	for e in entries:
		date = e["date"].split("T")[0]
		link = f"https://bsky.app/profile/{e['handle']}"
		rows.append(
			f"<tr><td><a href='{link}'>{e['handle']}</td>"
			f"<td>{e['mtld']:.1f}</td>"
			f"<td>{e['posts']}</td>"
			f"<td>{date}</td></tr>"
		)
	html = f"""<!doctype html>
<html lang="en">
<head>
<title>MTLD Results</title>
<style>
  body {{ font-family: sans-serif; margin: 2em; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
  th {{ background: #eee; }}
</style>
</head>
<body>
<h1>MTLD Results</h1>
<p><form action="/mtld" method="get">
 <input type="text" name="handle" placeholder="lucent.social">
 <button type="submit">Analyze</button>
</form></p>

<table>
<tr><th>Handle</th><th>MTLD</th><th>Posts</th><th>Last Pull</th></tr>
{''.join(rows)}
</table>
<p>MTLD (Measure of Textual Lexical Diversity) estimates vocabulary variety by counting on average how many words you string together before fewer than 72% of them are unique. The metric is relatively stable across passage lengths. Tokens are normalized to their lemma, so run/runs/running are all one verb, while runner is a separate noun. Proper nouns and anything out-of-vocabulary (usernames, misspellings) are skipped and do not affect the score.</p>
</body>
</html>"""
	with open(HTML_PATH, "w", encoding="utf-8") as f:
		f.write(html)

@app.route("/")
def index():
	return redirect("/static/index.html")

@app.route("/mtld", methods=["GET"])
def mtld_route():
	handle = request.args.get("handle")
	if not handle:
		return redirect("/static/index.html")

	cache = load_cache()
	if handle in cache:
		return redirect("/static/index.html")

	textfile = fetch_with_bash(handle, POST_LIMIT)
	text = open(textfile, "r", encoding="utf-8").read()
	tokens = preprocess_text(text)
	mtld = compute_mtld(tokens)

	entry = {
		"handle": handle,
		"date": now_iso(),
		"posts": POST_LIMIT,
		"mtld": mtld,
	}
	cache[handle] = entry
	save_cache(cache)
	build_html(cache)

	return redirect("/static/index.html")

if __name__ == "__main__":
	port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
	app.run(host="0.0.0.0", port=port)
