# ScreenPilot — Gemini Live Agent Challenge Submission

ScreenPilot is a full-stack web agent that watches a real browser session, reasons over screenshots with Gemini, and executes browser actions with Playwright to complete user goals.

## URL to Public Code Repository

Replace this with your public repo before submission:

`https://github.com/WoutBoonenPXL/Gemini-Live-Agent-Challenge`

## Text Description

### Features and functionality

- Goal-driven browser automation from natural language instructions.
- Real-time backend-to-frontend updates over WebSocket (`status`, `thinking`, `action`, `screenshot`, `error`).
- Playwright-driven execution of structured actions (`click`, `type`, `scroll`, `navigate`, `wait`, `done`, `ask_user`).
- Loop guard to stop repeated identical actions on unchanged screens.
- One-step quota-safe mode (`AGENT_MAX_STEPS=1`) for controlled usage.
- Rate-limit fail-fast behavior with retries and clear user-facing guidance.
- Cloud deployment on Google Cloud Run (frontend + backend).

### Technologies used

- **Backend**: Python 3.11, FastAPI, WebSockets, Pydantic.
- **Agent runtime**: Google ADK + custom session loop.
- **Model SDK**: `google.genai` (Gemini client).
- **Browser automation**: Playwright (Chromium).
- **Frontend**: Next.js 14, React, TypeScript, Tailwind CSS.
- **Cloud**: Google Cloud Run, Cloud Build, Artifact Registry.
- **Auth/config**: `.env` settings + GCP service account IAM.

### Other data sources used

- No private or third-party datasets are ingested.
- Runtime inputs are:
  - User goal text.
  - Live browser screenshots captured from Playwright.
  - Recent action history within the same session.
- Optional external page data is only what the browser visits during user-requested tasks.

### Findings and learnings

- Deployment reliability improved by excluding local `node_modules` from Docker context (`frontend/.dockerignore`).
- Cloud Run frontend builds can fail if `public/` is missing when Dockerfile copies it; adding `frontend/public/.gitkeep` resolved this.
- WebSocket transport and screenshot streaming worked correctly in production; the main runtime risk was model availability/permissions.
- Vertex model availability can differ by project/region; configured model IDs must be validated against actual project access.
- Explicit loop-detection and fail-fast quota behavior significantly improve user experience vs. silent retries.

## Spin-up Instructions (Reproducible)

### Prerequisites

- Python 3.11+
- Node.js 20+
- Google Cloud SDK (`gcloud`)
- A Google Cloud project with Vertex AI access

### 1) Clone the repository

```bash
git clone https://github.com/WoutBoonenPXL/Gemini-Live-Agent-Challenge.git
cd Gemini-Live-Agent-Challenge
```

### 2) Backend setup

```bash
cd backend
python -m venv venv
```

Windows:

```powershell
venv\Scripts\activate
```

macOS/Linux:

```bash
source venv/bin/activate
```

Install dependencies and browser:

```bash
pip install -r requirements.txt
playwright install chromium
```

Create `backend/.env`:

```env
USE_VERTEX=true
GCP_PROJECT_ID=gen-lang-client-0525160177
VERTEX_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash
GEMINI_MODEL_FALLBACKS=gemini-2.5-flash-lite
AGENT_MAX_STEPS=1
```

Run backend:

```bash
python run.py
```

Verify:

```bash
curl http://localhost:8000/health
```

### 3) Frontend setup

```bash
cd ../frontend
npm install
```

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_BACKEND_HTTP_URL=http://localhost:8000
NEXT_PUBLIC_BACKEND_WS_URL=ws://localhost:8000/ws
```

Run frontend:

```bash
npm run dev
```

Open `http://localhost:3000`.

### 4) Cloud Run deployment (same setup used in this project)

Authenticate and set project:

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project gen-lang-client-0525160177
```

Deploy backend:

```bash
gcloud run deploy screenpilot-backend \
  --source backend \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars USE_VERTEX=true,GCP_PROJECT_ID=gen-lang-client-0525160177,VERTEX_LOCATION=us-central1,GEMINI_MODEL=gemini-2.5-flash,GEMINI_MODEL_FALLBACKS=gemini-2.5-flash-lite,AGENT_MAX_STEPS=1
```

Deploy frontend (replace `<BACKEND_URL>`):

```bash
gcloud run deploy screenpilot-frontend \
  --source frontend \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars NEXT_PUBLIC_BACKEND_HTTP_URL= https://screenpilot-backend-950824668815.us-central1.run.app,NEXT_PUBLIC_BACKEND_WS_URL= https://screenpilot-backend-950824668815.us-central1.run.app/ws
```

Grant Vertex permission to backend service account:

```bash
gcloud projects add-iam-policy-binding <YOUR_GCP_PROJECT_ID> \
  --member="serviceAccount:<BACKEND_SERVICE_ACCOUNT>" \
  --role="roles/aiplatform.user"
```

## Notes for Judges

- The project is reproducible using the commands above.
- Backend health endpoint: `/health`.
- Frontend and backend are independently deployable to Cloud Run.

