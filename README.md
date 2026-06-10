# Project Evolve - Fair and Transparent Faculty Evaluation Framework

Project Evolve is an academic prototype for AI-assisted faculty evaluation. It combines multi-source data aggregation, NLP-based feedback analysis, explainable AI, fairness auditing, and blockchain-based audit logging through a FastAPI backend and Next.js dashboard.

## Main components

- **Data layer:** public datasets plus synthetic institutional data for faculty profiles, feedback, peer reviews, performance metrics, course materials, service, professional development, and audit records.
- **AI/NLP layer:** sentiment and topic analysis of student feedback, plus multi-factor scoring.
- **XAI layer:** SHAP and LIME explanations for traceable evaluation factors.
- **Fairness layer:** demographic parity, group score gaps, intersectional summaries, and injected-bias detection.
- **Blockchain layer:** private Ganache/Web3 audit trail for tamper-evident evaluation records.
- **Frontend:** dashboard, faculty details, XAI explanation views, fairness reports, validation reports, audit trail, ethics page, and trust-feedback collection.

## Setup

1. Create and activate a Python environment.
2. Install backend requirements:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and update database/blockchain values.
4. Run the notebooks in order to create and populate the database:

```text
01_Data_Layer_Phase1.ipynb
2_AI_Layer_Phase.ipynb
03_XAI_Layer_Phase.ipynb
04_Blockchain_Layer_Phase.ipynb
05_API_Layer_Phase.ipynb
```

5. Start the backend:

```bash
uvicorn src.api.main:app --reload
```

6. Start the frontend:

```bash
cd frontend
npm install
npm run dev
```

## Important prototype limitations

- Expert-human validation is simulated unless real expert evaluation scores are collected.
- Controlled trial mode is represented by validation reports and `PROJECT_EVOLVE_PARALLEL_MODE=True`; a real one-year parallel trial still requires institutional deployment.
- Ganache is used as a private blockchain prototype, not a production permissioned blockchain network.
- Teaching-quality and online-teaching datasets are integrated as supplementary sources; the current active scoring pipeline mainly uses RateMyProfessor-derived feedback plus synthetic institutional data.

## Presentation note

Describe this as a complete academic prototype, not a production-ready decision system. The correct wording is: "Project Evolve demonstrates a fair, transparent, AI-assisted faculty evaluation framework using multi-source data, XAI, fairness audits, and blockchain audit logging."
