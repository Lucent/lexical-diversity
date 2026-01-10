# Bluesky MTLD Analyzer

Analyzes lexical diversity of Bluesky accounts using MTLD (Measure of Textual Lexical Diversity). MTLD estimates vocabulary variety by counting how many words you string together on average before fewer than 72% are unique.

## What it does

- Fetches recent posts from Bluesky accounts
- Computes MTLD scores using lemmatized tokens
- Caches results and displays a sortable leaderboard
- Queue system for background processing

## Deploy with Docker

```bash
docker-compose up -d
```

Access at http://localhost:5000

## Manual deployment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_lg
python app.py
```
