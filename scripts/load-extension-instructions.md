# Loading the Niwas extension in Chrome

1. Open `chrome://extensions`.
2. Enable **Developer mode** (top right).
3. Click **Load unpacked** and choose the `extension/` folder in this repo.
4. Open any YouTube video. A floating panel labelled **"Niwas Fact Check"** appears.
5. Click **Start** in the panel (or use the toolbar popup).

If you change `extension/lib/config.js` or any other file, click the **reload** ↻ button on the extension card.

## Backend

In a separate terminal:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

Without API keys the backend still runs — verdicts return as `unverified` (mock mode), but the full pipeline (caption ingest → claim segmentation → Wikipedia retrieval → response) executes end-to-end.
