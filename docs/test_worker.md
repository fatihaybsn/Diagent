# Celery Worker Manuel Test

Aşağıdaki adımlar, Redis broker + Celery worker pipeline'ının uçtan uca çalıştığını doğrular.

## Ön Koşullar

- Docker ve Docker Compose kurulu olmalı
- Proje kök dizininde `.env` dosyası oluşturulmuş olmalı (`.env.example`'dan kopyalanabilir)

## 1. Servisleri Başlat

```bash
docker compose up --build
```

Dört servis ayağa kalkacak: `postgres`, `redis`, `api`, `worker`.

Tüm servislerin hazır olduğunu teyit et:

| Servis   | Beklenen Log                                      |
|----------|---------------------------------------------------|
| postgres | `database system is ready to accept connections`  |
| redis    | `Ready to accept connections`                     |
| api      | `Uvicorn running on http://0.0.0.0:8000`          |
| worker   | `celery@... ready.`                               |

## 2. Migration'ları Çalıştır (gerekirse)

API container'ına bağlan ve Alembic migration'ını çalıştır:

```bash
docker compose exec api alembic upgrade head
```

## 3. Yeni Bir Run Oluştur

```bash
curl -s -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "test-bot", "input": "merhaba dünya"}' | python -m json.tool
```

Yanıttaki `id` değerini not al. Örnek:

```json
{
    "id": "a1b2c3d4-...",
    "status": "running",
    ...
}
```

## 4. Run'ı Finish Et

Not aldığın `id`'yi kullanarak finish endpoint'ini çağır:

```bash
curl -s -X POST http://localhost:8000/runs/<RUN_ID>/finish | python -m json.tool
```

Beklenen yanıt:

```json
{
    "id": "<RUN_ID>",
    "status": "finished",
    "duration_ms": ...,
    ...
}
```

## 5. Worker Logunu Kontrol Et

Worker container loglarını kontrol et:

```bash
docker compose logs worker
```

Aşağıdaki satırı görmelisin:

```
worker-1  | [INFO] diagent.workers.tasks: echo task — run_id=<RUN_ID>  status=finished  (DB connection OK)
```

Bu log satırı iki şeyi kanıtlar:
1. Finish endpoint'i Celery task'ını başarıyla Redis'e gönderdi ve worker işledi
2. Worker, Postgres'e bağlanıp run kaydını okuyabildi (`status=finished`, `DB connection OK`)

## 6. (Opsiyonel) Redis'i Doğrula

Redis'e bağlanarak task sonucunu kontrol edebilirsin:

```bash
docker compose exec redis redis-cli KEYS "celery-task-meta-*"
```

Finish çağrısından sonra en az bir key görmelisin.

## Temizlik

```bash
docker compose down -v
```

`-v` flag'i volume'ları da siler (postgres verisi dahil).
