# Dental AI Web App

A responsive pure HTML/CSS/JavaScript dashboard backed by FastAPI, the trained YOLOv8 Medium model, OpenCV preprocessing, SQLite case history, OpenAI reporting, and PDF export.

## Run locally

From `Dental_AI_Web_App`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
uvicorn backend.main:app --reload --port 8000
```

Open `http://localhost:8000/app/`. The backend serves the frontend in this local configuration. If hosting the frontend separately, set `window.DENTAL_API_BASE` before loading `script.js` or replace the default API URL in `frontend/script.js`.

Put the model at `backend/model/best.pt`. The weights file is intentionally excluded from this repository because it is larger than GitHub's regular 100 MB file limit; obtain it separately before running inference. The project expects the existing model's four classes: Fillings, Implant, Cavity, and Impacted Tooth. `OPENAI_API_KEY` is read only by the backend; when it is empty, a deterministic local report is generated.

For Render or Railway, use `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`. For Vercel, deploy `frontend` as a static site and point the API base at the deployed backend.
