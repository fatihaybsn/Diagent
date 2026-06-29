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
├── core/                    # Framework-agnostic çekirdek
│   ├── tracer.py
│   ├── anomaly_detector.py
│   ├── rag_quality.py
│   └── diagnostician.py
├── adapters/
│   ├── demo_support_bot/    # Kavramsal demo
│   └── pathfinder_ship/     # Gerçek entegrasyon (Adım 9)
├── api/                     # FastAPI routers
├── models/                  # SQLAlchemy ORM modelleri
├── workers/                 # Celery task'ları
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
4. `cost_spike` $/token mantığına dayanır; PathFinder-Ship adaptörü `latency_spike` kullanır
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
POST   /runs/{id}/finish        ← anomaly detection + RAG evaluation task'larını tetikler (retrieval olan run'larda)
POST   /evaluations/run/{id}
GET    /evaluations/run/{id}
GET    /diagnoses/{run_id}
GET    /alerts?run_id={uuid}    (opsiyonel — belirtilmezse tüm alert'ler döner)
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

## Tamamlanan Adımlar

### ✅ ADIM 1 — Şema & SDK Tasarımı
- Veritabanı tabloları tasarlandı (agents, runs, spans, tool_calls, retrievals, evaluations, diagnoses, alerts)
- Pydantic request/response şemaları oluşturuldu
- `docs/SCHEMA.md` dokümantasyonu yazıldı

### ✅ ADIM 2 — DB + FastAPI İskeleti
- PostgreSQL + Alembic migration altyapısı kuruldu
- SQLAlchemy ORM modelleri yazıldı
- FastAPI router'ları oluşturuldu (runs CRUD, spans, finish, healthz)
- **Kriter:** `curl -X POST localhost:8000/runs -d '{"agent_name":"test"}'` çalışır, Postgres'te kaydı görürsün ✔️

### ✅ ADIM 3 — Redis + Celery Worker İskeleti
- `docker-compose.yml`'e Redis servisi eklendi
- `workers/celery_app.py`: Celery app oluşturuldu (broker=Redis)
- `workers/tasks.py`: `echo` dummy task yazıldı (run_id'yi loglar, Postgres'e bağlanıp doğrular)
- `POST /runs/{id}/finish` endpoint'i güncellendi: status="finished" + echo Celery task'ı tetikler
- `docker-compose.yml`'e worker servisi eklendi (api ile aynı image, `celery worker` komutu)
- Dockerfile oluşturuldu (python:3.12-slim, api ve worker ortak image)
- `docs/test_worker.md` manuel test talimatı yazıldı
- **Kriter:** POST /runs/{id}/finish sonrası Celery worker logunda task çalıştığı görünür. Worker Postgres'e bağlanabiliyor ✔️

### ✅ ADIM 4 — Tracer SDK + Demo Agent
- `core/tracer.py`: `DiagentTracer` HTTP client, `@observe` decorator, `log_tool_call()`, `log_retrieval()`, `log_span()` — context var ile aktif run_id paylaşımı
- API'ye yeni endpoint'ler eklendi: `POST /runs/{id}/tool_calls`, `POST /runs/{id}/retrievals`
- `POST /runs/{id}/finish` artık opsiyonel body kabul eder (`output`, `total_tokens`, `cost_usd`)
- `adapters/demo_support_bot/agent.py`: Mock müşteri destek agent'ı (retrieve → llm → tool → answer)
- `scripts/seed_demo_data.py`: 3 senaryo (normal, tool error ×3, tool loop ×5)
- `scripts/seed_synthetic_data.py`: 4 edge case (tool_loop ×8, cost_spike 10x, stale_data 96h, tool_failure all-error)
- **Kriter:** Seed scriptleri çalıştıktan sonra GET /runs en az 7 farklı run döner (toplam 8 run: 3 demo + 5 synthetic) ✔️

### ✅ ADIM 5 — Rule-Based Detector'lar
- `diagent/core/anomaly_detector.py`: 6 adet kural tabanlı dedektör fonksiyonu ve `run_all_detectors` orkestratör fonksiyonu implement edildi.
- `diagent/workers/tasks.py`: `run_anomaly_detection` Celery task'ı yazıldı ve `POST /runs/{id}/finish` endpoint'i ile entegre edildi.
- `diagent/api/routes/alerts.py` ve `GET /alerts` endpoint'i implement edilip FastAPI uygulamasında kaydedildi.
- Testler her dedektör için ayrı dosyalarda trigger/no-trigger senaryolarıyla yazıldı (`tests/test_detector_*.py`).
- **Kriter:** `pytest tests/test_detector_*` hepsi yeşil ✔️ ve `GET /alerts` çağrısı seed data'daki bozuk run'lar için alert dönüyor ✔️

### ✅ ADIM 6 — RAG Quality Evaluation
- `diagent/core/rag_quality.py`: `JudgeLLM` abstract interface'i, `OpenAIJudge` ve `OllamaJudge` implementasyonları eklendi.
- Judge prompt'ları RAGAS yaklaşımına uygun olarak `faithfulness`, `answer_relevancy`, `context_precision` metriklerini 0.0-1.0 arası skorlayacak şekilde yazıldı.
- `overall_score`, üç metriğin ortalaması olarak hesaplanıyor.
- `diagent/workers/tasks.py`: `run_rag_evaluation(run_id)` Celery task'ı eklendi; sadece `retrievals` kaydı olan run'ları değerlendiriyor ve skorları `evaluations` tablosuna yazıyor.
- `JUDGE_RATE_LIMIT_SECONDS` env değişkeniyle judge LLM çağrıları arasına minimum bekleme eklendi (default: 1 saniye).
- `diagent/api/routes/evaluations.py`: `POST /evaluations/run/{id}` endpoint'i eklendi ve `run_rag_evaluation` task'ını tetikliyor.
- `GET /runs/{id}` response'una son evaluation sonucu `evaluation` alanı olarak eklendi.
- OpenAI/API backend ve Ollama backend mock HTTP testleriyle doğrulandı.
- **Kriter:** `POST /evaluations/run/{id}` sonrası worker task tamamlandığında `GET /runs/{id}` içinde `faithfulness`, `answer_relevancy`, `context_precision`, `overall_score` görünür ✔️
- RAG evaluation artık POST /runs/{id}/finish tarafından otomatik tetikleniyor (retrieval olan run'larda); POST /evaluations/run/{id} endpoint'i yine de manuel tetikleme için kullanılabilir
- **Test:** `pytest` → 20 test yeşil ✔️

### ✅ ADIM 7 — Diagnostician Agent
- `diagent/core/diagnostician.py`: LangGraph tabanlı 2-node diagnostician graph eklendi (`gather_evidence → reason`).
- `gather_evidence` node'u salt-okunur araçlarla veri topluyor: `get_run_details(run_id)`, `get_alerts(run_id)`, `get_evaluation_scores(run_id)`, `get_retrieval_info(run_id)`.
- `reason` node'u LLM'den zorunlu JSON formatında `root_cause`, `confidence`, `evidence`, `recommendation` alanlarını üretiyor.
- Diagnostician core katmanı veritabanına yazmıyor ve dış servis çağrısını worker tarafından verilen LLM interface'i üzerinden alıyor.
- `diagent/workers/tasks.py`: `run_diagnosis(run_id)` Celery task'ı eklendi; düşük RAG kalitesi ve çoklu alert koşulu sağlanınca diagnosis sonucunu `diagnoses` tablosuna yazıyor.
- `run_rag_evaluation(run_id)` tamamlandıktan sonra `overall_score < DIAGNOSIS_RAG_SCORE_THRESHOLD` ve birden fazla alert varsa `run_diagnosis` otomatik tetikleniyor.
- `DIAGNOSIS_RAG_SCORE_THRESHOLD=0.6` env ayarı eklendi.
- `diagent/api/routes/diagnoses.py`: `GET /diagnoses/{run_id}` endpoint'i eklendi ve FastAPI uygulamasına kaydedildi.
- `requirements.txt` içine `langgraph>=0.2.0` eklendi.
- Testler düşük skorlu + birden fazla alert içeren seed run için diagnosis kaydının oluştuğunu ve RAG evaluation sonrası diagnosis task'ının otomatik kuyruğa alındığını doğruluyor.
- **Kriter:** `GET /diagnoses/{run_id}` → `root_cause`, `confidence`, `evidence`, `recommendation` döner ✔️
- **Test:** `pytest` → 22 test yeşil ✔️

### ✅ ADIM 8 — Docker Compose + README Finalizasyonu
- `docker-compose.yml`: 4 servisli final compose yapısı hazırlandı (`api`, `worker`, `postgres`, `redis`).
- `api` ve `worker` aynı `Dockerfile` üzerinden build ediliyor; `api` FastAPI/Uvicorn komutuyla, `worker` Celery worker komutuyla başlıyor.
- `postgres` ve `redis` için health check eklendi; `api` ve `worker`, `depends_on` ile iki servisin healthy olmasını bekliyor.
- `api` başlangıcında `alembic upgrade head` çalıştırılarak temiz Postgres üzerinde tablolar otomatik kuruluyor.
- `Dockerfile`: Python 3.12 slim single-stage image olarak finalize edildi; `PYTHONPATH=/app` eklendi.
- `.env.example`: compose portları, Postgres bootstrap değerleri, app URL'leri, judge backend ayarları, detector threshold'ları, diagnostician threshold'u ve worker log seviyesi belgelendi.
- `diagent/config.py`: `.env.example` içindeki compose/worker-only değişkenleri uygulamayı kırmasın diye Pydantic settings `extra="ignore"` yapıldı.
- `diagent/workers/tasks.py`: worker sync DB bağlantısı kurulu bağımlılıkla uyumlu olacak şekilde `postgresql+psycopg2://` kullanıyor.
- `README.md`: tek paragraflık proje açıklaması, `git clone → cp .env.example .env → docker compose up` kurulumu, temel curl örnekleri ve `@diagent.observe` örneği eklendi.
- `diagent/__init__.py`: README'deki `diagent.observe`, `diagent.log_retrieval`, `diagent.log_tool_call` örneği doğrudan çalışsın diye tracer helper'ları paket kökünden export edildi.
- Temiz geçici clone üzerinden Docker akışı test edildi; bu makinede `8000` portu başka container tarafından dolu olduğu için doğrulama `API_PORT=18000` ile yapıldı.
- **Kriter:** Temiz ortamda `docker compose up` + `python -m scripts.seed_synthetic_data` + `curl localhost:8000/alerts` alert listesi döndürür ✔️
- **Test:** Temiz clone'da compose build/up, seed script ve `/alerts` doğrulandı; `tool_loop`, `cost_spike`, `stale_data`, `tool_failure` alert'leri döndü ✔️
