# Diagent — CLAUDE.md

## Proje Özeti
Self-hosted AI agent ve RAG observability backend'i.
Portfolio/staj odaklı, bitirilebilir MVP. Tek `docker compose up` ile çalışır.

## Tech Stack
- **API:** FastAPI (async) + Swagger otomatik
- **DB:** PostgreSQL + Alembic (migration aracı)
- **Queue:** Redis broker + Celery worker
- **Agent:** LangGraph (2-node: gather_evidence → reason)
- **RAG eval:** RAGAS yaklaşımı (faithfulness, answer_relevancy, context_precision)
- **Deploy:** Docker Compose (4 servis: api, worker, postgres, redis)

## Klasör Yapısı
```
diagent/
├── core/
│   ├── tracer.py
│   ├── anomaly_detector.py
│   ├── rag_quality.py
│   └── diagnostician.py
├── adapters/
│   └── demo_support_bot/
├── api/
├── models/
├── workers/
├── tests/
│   ├── conftest.py
│   └── test_detector_*.py
├── alembic/
├── docker-compose.yml
├── .env.example
└── requirements.txt
```

## Mimari Kurallar — ASLA İHLAL ETME
1. `core/` hiçbir adapter'a import yapmaz, hiçbir projeye özel kod içermez
2. Eşik değerleri (loop kaç kez, spike kaç kat) hardcode edilmez — .env / config'den okunur
3. Diagnostician agent SALT-OKUNUR; veritabanına yazma, dış servis çağırma yetkisi yok
4. `cost_spike` $/token mantığına dayanır
5. Proje-spesifik mantık `adapters/` altında kalır, `core/`'a karışmaz

## Veritabanı Tabloları
```
agents       → id, name, version, created_at
runs         → id, agent_id, input, output, status, duration_ms, total_tokens, cost_usd, created_at
spans        → id, run_id, type(llm_call|tool_call|retrieval|system), name, started_at, ended_at, duration_ms, payload(JSONB)
tool_calls   → id, run_id, tool_name, args(JSONB), status, error, duration_ms
retrievals   → id, run_id, query, retrieved_chunks(JSONB), top_k, source_age_hours
evaluations  → id, run_id, faithfulness, answer_relevancy, context_precision, overall_score, created_at
diagnoses    → id, run_id, root_cause, confidence, evidence(JSONB), recommendation, created_at
alerts       → id, run_id, type, severity, message, created_at
```

## API Endpoints (V1)
```
POST   /runs
GET    /runs
GET    /runs/{id}
POST   /runs/{id}/spans
POST   /runs/{id}/tool_calls
POST   /runs/{id}/retrievals
POST   /runs/{id}/finish
POST   /evaluations/run/{id}
GET    /evaluations/run/{id}
GET    /diagnoses/{run_id}
GET    /alerts?run_id={uuid}
GET    /healthz
```

## Anomaly Tipleri
`tool_loop | tool_failure | cost_spike | latency_spike | stale_data | empty_retrieval`

## Diagnosis root_cause Değerleri
`stale_document | weak_retrieval | tool_failure | tool_loop | cost_spike | answer_not_grounded | unknown`

## Test Kuralı
Her detector için 2 test zorunludur:
1. Detector'ı TETİKLEMESİ gereken run
2. Detector'ı TETİKLEMEMESİ gereken run (false positive kontrolü)

Eşik değerleri test ortamında env override ile değiştirilebilir olmalı.

## Kapsam Dışı — Yazmayacağız
- Frontend / React dashboard
- Multi-tenant auth
- PyPI paketi
- Otomatik düzeltme / reindexing
- LangChain / LlamaIndex / CrewAI adapter'ları
- Kubernetes deployment
- Slack webhook (V2'ye bırakıldı)

## Judge LLM Konfigürasyonu
`DIAGENT_JUDGE_BACKEND=openai` veya `=ollama`
`core/` sadece `JudgeLLM` interface'ini bilir, hangi backend olduğunu bilmez.
