# TruthGuard — AI-assisted fact-checking website

TruthGuard is a Flask web app that investigates a user-submitted claim using:
1. Google's Fact Check Tools API (matching fact-check reviews and publisher ratings).
2. Tavily Search API (live web search results and snippets).

It intentionally avoids pretending that an unsupported claim is automatically fake. The result is a research snapshot, not a definitive truth judgement.

## Requirements
- Python 3.10+
- Internet connection
- API keys (recommended for full functionality)

## Setup (Windows PowerShell)

```powershell
cd truthguard
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and add your keys:
- `GOOGLE_FACTCHECK_API_KEY` — enable the Fact Check Tools API in a Google Cloud project and create an API key.
- `TAVILY_API_KEY` — create a key at https://tavily.com/.

Then run:

```powershell
python app.py
```

Open http://127.0.0.1:5000 in your browser.

## Setup (macOS / Linux)

```bash
cd truthguard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your API keys
python app.py
```

Open http://127.0.0.1:5000.

## API keys and functionality
- With both keys configured, each check queries fact-check reviews and live web search.
- With only one key, that source is used and the UI tells you which integrations are configured.
- With no keys, the app runs but cannot retrieve live evidence; configure keys for the intended full experience.
- Never commit `.env` or expose API keys in browser JavaScript. Keys are only read by the Python backend.

## Important limitations
- Search results are leads, not proof. Open the original source and check its author, date, evidence, and context.
- Similar wording does not guarantee the fact-check refers to the exact same claim.
- A lack of results means “not verified here,” not “fake.”
- This starter does not detect deepfakes or authenticate images/videos.
- Before public deployment, add rate limiting, logging controls, abuse protection, HTTPS, and a production WSGI server. Do not use Flask's development server in production.

## Project structure

```
truthguard/
  app.py
  requirements.txt
  .env.example
  templates/
    index.html
  static/
    style.css
    app.js
  README.md
```

## Quick test
Paste a specific, checkable statement (include date/place where relevant) and press **Investigate claim**. The report displays publisher ratings, search-result snippets, and links to original pages.
