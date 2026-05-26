# Autonomous Browser Agent

> AI-powered autonomous browser system — plan, navigate, extract, reason, and recover like a human.

---

## Architecture

```
User Prompt
    ↓
FastAPI Backend  (localhost:8000)
    ↓
Planner Agent  ←── Groq LLM (llama-3.3-70b-versatile)
    ↓
LangGraph StateGraph
    ├── PlannerNode     → breaks prompt into ordered steps
    ├── RouterNode      → detects task type (job_search / pdf / browser)
    ├── JobSearchNode   → scrapes Internshala, Wellfound, RemoteOK
    ├── BrowserNode     → browser-use + Playwright autonomous control
    ├── PDFNode         → download + PyMuPDF + LLM summary
    ├── ExtractorNode   → structures raw page text → JSON
    ├── MemoryNode      → stores results in ChromaDB
    └── OutputNode      → returns final structured response
    ↓
Groq LLM  (deepseek-r1-distill-llama-70b for reasoning)
    ↓
Structured JSON Output  →  Frontend display
```

---

## Tech Stack

| Layer            | Technology                                    |
|------------------|-----------------------------------------------|
| Frontend         | Vanilla HTML · CSS · JavaScript (no framework)|
| Backend API      | FastAPI + Uvicorn                             |
| AI Orchestration | LangGraph StateGraph                          |
| LLM              | Groq API — llama-3.3-70b / deepseek-r1-70b   |
| Browser          | Playwright + browser-use                      |
| Memory           | ChromaDB (persistent vector store)            |
| PDF              | PyMuPDF (fitz)                                |
| Language         | Python 3.11+                                  |

---

## Folder Structure

```
browser agent/
│
├── backend/
│   ├── main.py                      # FastAPI app entry point
│   ├── config/
│   │   ├── settings.py              # Pydantic settings from .env
│   │   └── logging_config.py        # Rotating file + console logging
│   ├── routes/
│   │   ├── task_routes.py           # POST /api/task, SSE /api/task/{id}/logs
│   │   ├── upload_routes.py         # POST /api/upload-resume
│   │   └── history_routes.py        # GET /api/history/jobs, /search
│   ├── agents/
│   │   ├── orchestrator.py          # LangGraph StateGraph (central brain)
│   │   ├── planner_agent.py         # Prompt → execution plan
│   │   ├── browser_agent.py         # browser-use + Playwright control
│   │   ├── extraction_agent.py      # Raw text → structured JSON
│   │   ├── resume_agent.py          # PDF → candidate profile
│   │   ├── recovery_agent.py        # Failure analysis + retry strategy
│   │   └── memory_agent.py          # ChromaDB read/write
│   ├── tools/
│   │   ├── job_search_tool.py       # Multi-portal job scraper
│   │   ├── web_nav_tool.py          # Generic navigation helper
│   │   ├── form_fill_tool.py        # Auto form detection + filling
│   │   ├── pdf_tool.py              # PDF download + analysis
│   │   ├── extraction_tool.py       # HTML/JSON-LD/table extractor
│   │   └── memory_tool.py           # ChromaDB CRUD wrapper
│   ├── memory/
│   │   ├── chroma_store.py          # Singleton ChromaDB manager
│   │   └── schemas.py               # Job/Task/Search record schemas
│   └── services/
│       ├── task_service.py          # Async task registry + lifecycle
│       └── browser_service.py       # Playwright browser lifecycle
│
├── frontend/
│   ├── index.html                   # Single-page UI
│   ├── style.css                    # Dark terminal aesthetic
│   └── script.js                    # SSE streaming, results rendering
│
├── uploads/                         # Uploaded resume PDFs
├── logs/                            # Rotating log files
├── chroma_db/                       # ChromaDB persistent storage
├── requirements.txt
├── .env                             # Your API keys (copy from .env template)
└── README.md
```

---

## Setup

### 1. Clone / navigate to project

```bash
cd "browser agent"
```

### 2. Create virtual environment

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright browsers

```bash
playwright install chromium
```

### 5. Configure environment

Edit `.env` and set your Groq API key:

```env
GROQ_API_KEY=gsk_your_actual_key_here
```

Get a free key at: https://console.groq.com

### 6. Run the server

```bash
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 7. Open the UI

Navigate to: **http://localhost:8000**

API docs at: **http://localhost:8000/api/docs**

---

## Usage Examples

### Job Search
```
Find remote GenAI internships on Internshala and Wellfound
```
```
Search AI/ML internship opportunities — collect company, role, salary, skills
```
```
Find Python backend developer jobs — focus on RAG and LLM roles
```

### Web Navigation
```
Open https://example.com and extract all the main information
```
```
Navigate to RemoteOK and find the top AI jobs posted this week
```

### PDF Analysis
```
Download and summarize the PDF at https://example.com/report.pdf
```

### Resume Upload
Use the **Resume** tab to upload your PDF resume.
The agent will extract: name, email, phone, skills, experience, education, GitHub, LinkedIn.

---

## API Endpoints

| Method   | Endpoint                       | Description                        |
|----------|--------------------------------|------------------------------------|
| `POST`   | `/api/task`                    | Submit a new agent task            |
| `GET`    | `/api/task/{id}`               | Poll task status + results         |
| `GET`    | `/api/task/{id}/logs`          | SSE stream of live agent logs      |
| `DELETE` | `/api/task/{id}`               | Cancel a running task              |
| `GET`    | `/api/tasks`                   | List recent tasks                  |
| `POST`   | `/api/upload-resume`           | Upload and parse a PDF resume      |
| `GET`    | `/api/resume`                  | Get current resume profile         |
| `GET`    | `/api/history/jobs`            | All stored job listings            |
| `GET`    | `/api/history/search?q=query`  | Semantic search in memory          |
| `DELETE` | `/api/history?collection=jobs` | Clear a memory collection          |
| `GET`    | `/health`                      | Server health check                |
| `GET`    | `/api/docs`                    | Swagger UI                         |

### Task request body
```json
{
  "prompt": "Find remote GenAI internships",
  "max_steps": 20,
  "headless": false
}
```

### Task response
```json
{
  "task_id": "uuid",
  "status": "pending",
  "message": "Task queued successfully."
}
```

### Job result format
```json
[
  {
    "company": "TechCorp",
    "role": "GenAI Intern",
    "location": "Remote",
    "salary": "₹15,000/month",
    "skills": ["Python", "LangChain", "RAG"],
    "apply_link": "https://...",
    "job_type": "internship",
    "source": "Internshala"
  }
]
```

---

## Agent Behaviour

| Scenario              | Behaviour                                                   |
|-----------------------|-------------------------------------------------------------|
| Timeout               | Retry up to 3× with exponential backoff                     |
| Element not found     | Try alternative selectors, wait for dynamic content         |
| Rate limited (429)    | Back off 30s, retry                                         |
| Access denied (403)   | Skip portal, continue with others                           |
| LLM extraction fails  | Fallback to regex / BeautifulSoup parsing                   |
| browser-use unavail.  | Fallback to direct Playwright control                       |
| Max retries exceeded  | Skip step, log warning, continue with next                  |

---

## Memory Collections (ChromaDB)

| Collection     | Contents                                          |
|----------------|---------------------------------------------------|
| `agent_memory` | Task prompts and result summaries                 |
| `jobs`         | Deduplicated job listings with metadata           |
| `searches`     | Recorded search queries and sources               |

---

## Requirements

- Python 3.11+
- Windows / Mac / Linux
- Groq API key (free tier works)
- Chromium browser (installed via `playwright install chromium`)

---

## License

MIT
