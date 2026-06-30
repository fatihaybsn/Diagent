# Diagent

Diagent, self-hosted AI agent ve RAG observability backend'idir; FastAPI, PostgreSQL, Redis, Celery, rule-based anomaly detector'lar, RAG quality evaluation ve read-only diagnostician agent ile agent run'larını, tool call'ları, retrieval kalitesini, alert'leri ve diagnosis sonuçlarını tek `docker compose up` akışında izlenebilir hale getirir.

Sisteminizi Diagent ile nasıl entegre edeceğinizi öğrenmek için [Diagent Integration Guide](docs/INTEGRATION_GUIDE.md) dokümanını inceleyebilirsiniz.

## Kurulum

```bash
git clone <repo-url>
cd Diagent
cp .env.example .env
docker compose up
```

## Temel API Kullanımı

```bash
curl http://localhost:8000/healthz
```

```bash
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"demo-agent","input":"İade süresi nedir?"}'
```

```bash
curl -X POST http://localhost:8000/runs/<run_id>/tool_calls \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"refund_lookup","args":{"order_id":"A-123"},"status":"error","error":"TimeoutError","duration_ms":1200}'
```

```bash
curl -X POST http://localhost:8000/runs/<run_id>/finish \
  -H "Content-Type: application/json" \
  -d '{"output":"İade işlemi şu anda doğrulanamıyor.","total_tokens":240,"cost_usd":0.002}'
```

```bash
curl http://localhost:8000/alerts
```

## `@diagent.observe` Örneği

```python
import diagent


@diagent.observe(agent_name="support-bot")
def answer_customer(question: str) -> str:
    diagent.log_retrieval(
        query=question,
        retrieved_chunks=[{"text": "İade süresi 14 gündür.", "source": "faq.md"}],
        top_k=3,
        source_age_hours=2,
    )
    diagent.log_tool_call(
        tool_name="refund_lookup",
        args={"question": question},
        status="success",
        duration_ms=180,
    )
    return "İade süresi 14 gündür."
```
