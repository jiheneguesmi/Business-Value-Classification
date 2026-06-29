#  Business Value Classifier

<img width="1880" height="1029" alt="dashboard" src="https://github.com/user-attachments/assets/14663288-a44c-405c-b368-7fce7efbbf37" />
<img width="1880" height="839" alt="analyse1" src="https://github.com/user-attachments/assets/6636c59a-0cf6-40ab-882a-212ebbb21a02" />
<img width="1886" height="585" alt="analyse2" src="https://github.com/user-attachments/assets/165dab06-f51c-43a3-b245-4077f7e9921a" />
<img width="1872" height="1002" alt="résultats métier" src="https://github.com/user-attachments/assets/da38ef0e-515f-4f8c-9010-31d517c88ca2" />
<img width="1878" height="996" alt="recommandations" src="https://github.com/user-attachments/assets/6825b2d9-6c6f-4924-a9a3-0c6ce2f12c32" />





> Intelligent system for analyzing persuasive value in B2B commercial documents using a Multi-LLM pipeline.

---

##  Overview

This project automatically extracts, structures, and classifies sentences from commercial PDF documents according to their **business value**, using a multi-model LLM approach with majority voting.

Each sentence is evaluated against **9 binary questions** across 3 business dimensions:

| Category | Description |
|---|---|
| **ROI** | Financial gains, cost reduction, operational efficiency |
| **Notoriety** | Image, attractiveness, user experience, well-being |
| **Obligation** | Regulatory constraints, security, compliance |
| **Description** | Neutral or purely informative content |

---

##  Architecture

```
PDF Documents
    └── Extraction (Marker: PDF → Markdown)
        └── Cleaning & Segmentation (spaCy)
            └── Multi-LLM Classification (5 models via OpenRouter)
                └── Majority Voting + Confidence Score
                    └── JSON / Excel / NumPy Export
                        └── React/Vite Web Application
```

---

##  Tech Stack

**Backend**
- Python, FastAPI
- [Marker](https://github.com/VikParuchuri/marker) — PDF to Markdown extraction
- spaCy — Linguistic segmentation (FR/EN)
- OpenRouter — Unified LLM API gateway
- Pandas, NumPy, OpenPyXL, Matplotlib

**Frontend**
- React + Vite
- TanStack Router & Query
- Recharts, Lucide React

**Models**
- `openai/gpt-4o-mini`
- `meta-llama/llama-3.3-70b-instruct`
- `google/gemma-3-27b-it`
- `mistralai/mistral-nemo`
- `qwen/qwen3-8b`

---

##  Key Results

- **8,987 sentences** classified across 23 clients
- **~80,000 observations** compared between context and no-context modes
- Global Cohen's Kappa: **0.69** between the two classification modes
- Inter-model agreement: **>96%** on Obligation, **~93%** on Notoriety
- Context mode costs **~84% more** but improves ambiguous sentence interpretation

---

##  Getting Started

### Prerequisites

```bash
python >= 3.10
node >= 18
```

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env  # add your OpenRouter API key
uvicorn server:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

##  Project Structure

```
├── backend/
│   ├── server.py               # FastAPI server
│   ├── work/                   # Pipeline outputs
│   └── uploads/                # Uploaded PDFs
├── classification_test/
│   ├── Extraction/             # PDF extraction scripts
│   ├── Decoupage/              # Cleaning & segmentation
│   ├── Classification/         # Prompts & classification scripts
│   └── analyse_comparative/    # CTX vs NOC analysis
└── frontend/
    └── src/                    # React application
```

---

## Application Features

-  Upload PDF documents
-  **Fast mode** — sentence-level classification (no context)
-  **Expert mode** — paragraph-context classification
-  Dashboard with category distribution
-  Filter & search classified sentences
-  Business summary with recommendations
-  Export results as CSV or JSON

---

##  License

This project was developed as part of a final engineering internship (PFE) at [CReSTIC](https://crestic.univ-reims.fr/), Université de Reims Champagne-Ardenne, in collaboration with [Chochoy Conseil](https://chochoy.fr/).

---

*Jihene Guesmi — IDS5, Faculté des Sciences de Tunis — 2025/2026*
