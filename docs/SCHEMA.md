# Diagent — Veritabanı Şeması & Tracer API

> Bu döküman `CLAUDE.md`'deki 8 tabloyu ayrıntılı olarak tanımlar,
> JSONB alanlarını işaretler ve `@diagent.observe` decorator'ının
> pseudocode imzalarını içerir.

---

## 1. Tablo Şemaları

### 1.1 `agents`

| Alan | Tip | Nullable | Açıklama |
|------|-----|----------|----------|
| `id` | `UUID` (PK) | ✗ | Benzersiz agent tanımlayıcısı |
| `name` | `VARCHAR(128)` | ✗ | Agent adı (unique, arama anahtarı) |
| `version` | `VARCHAR(32)` | ✗ | Semantik versiyon (ör. `"1.0.0"`) |
| `created_at` | `TIMESTAMPTZ` | ✗ | Kayıt oluşturulma zamanı, default `NOW()` |

---

### 1.2 `runs`

| Alan | Tip | Nullable | Açıklama |
|------|-----|----------|----------|
| `id` | `UUID` (PK) | ✗ | Benzersiz run tanımlayıcısı |
| `agent_id` | `UUID` (FK → `agents.id`) | ✗ | Bu run'ı başlatan agent |
| `input` | `TEXT` | ✗ | Kullanıcının gönderdiği sorgu/prompt |
| `output` | `TEXT` | ✓ | Agent'ın ürettiği yanıt (run bitince dolar) |
| `status` | `VARCHAR(16)` | ✗ | `running` · `finished` |
| `duration_ms` | `INTEGER` | ✓ | Toplam çalışma süresi (ms), run bitince hesaplanır |
| `total_tokens` | `INTEGER` | ✓ | Tüm LLM çağrılarının toplam token sayısı |
| `cost_usd` | `NUMERIC(10,6)` | ✓ | Tahmini maliyet ($/token üzerinden) |
| `created_at` | `TIMESTAMPTZ` | ✗ | Run başlangıç zamanı, default `NOW()` |

---

### 1.3 `spans`

| Alan | Tip | Nullable | Açıklama |
|------|-----|----------|----------|
| `id` | `UUID` (PK) | ✗ | Benzersiz span tanımlayıcısı |
| `run_id` | `UUID` (FK → `runs.id`) | ✗ | Ait olduğu run |
| `type` | `VARCHAR(16)` | ✗ | Span tipi — bkz. [Bölüm 4](#4-span-tipleri) |
| `name` | `VARCHAR(128)` | ✗ | Okunabilir etiket (ör. `"call_openai"`, `"search_docs"`) |
| `started_at` | `TIMESTAMPTZ` | ✗ | Span başlangıcı |
| `ended_at` | `TIMESTAMPTZ` | ✓ | Span bitişi (henüz bitmemişse `NULL`) |
| `duration_ms` | `INTEGER` | ✓ | Hesaplanan süre, `ended_at - started_at` |
| `payload` | **`JSONB`** 🔶 | ✓ | Span'a özgü serbest-form veri (prompt, response, metadata vb.) |

---

### 1.4 `tool_calls`

| Alan | Tip | Nullable | Açıklama |
|------|-----|----------|----------|
| `id` | `UUID` (PK) | ✗ | Benzersiz tool_call tanımlayıcısı |
| `run_id` | `UUID` (FK → `runs.id`) | ✗ | Ait olduğu run |
| `tool_name` | `VARCHAR(128)` | ✗ | Çağrılan tool'un adı (ör. `"web_search"`) |
| `args` | **`JSONB`** 🔶 | ✓ | Tool'a geçirilen argümanlar |
| `status` | `VARCHAR(16)` | ✗ | `success` · `error` |
| `error` | `TEXT` | ✓ | Hata mesajı (başarılıysa `NULL`) |
| `duration_ms` | `INTEGER` | ✓ | Tool çağrısının süresi (ms) |

---

### 1.5 `retrievals`

| Alan | Tip | Nullable | Açıklama |
|------|-----|----------|----------|
| `id` | `UUID` (PK) | ✗ | Benzersiz retrieval tanımlayıcısı |
| `run_id` | `UUID` (FK → `runs.id`) | ✗ | Ait olduğu run |
| `query` | `TEXT` | ✗ | RAG sorgusunda kullanılan metin |
| `retrieved_chunks` | **`JSONB`** 🔶 | ✓ | Dönen doküman chunk'ları listesi `[{text, score, source, ...}]` |
| `top_k` | `INTEGER` | ✗ | Kaç chunk istendiği |
| `source_age_hours` | `NUMERIC(10,2)` | ✓ | En eski chunk'ın yaşı (saat cinsinden, stale_data tespiti için) |

---

### 1.6 `evaluations`

| Alan | Tip | Nullable | Açıklama |
|------|-----|----------|----------|
| `id` | `UUID` (PK) | ✗ | Benzersiz evaluation tanımlayıcısı |
| `run_id` | `UUID` (FK → `runs.id`) | ✗ | Değerlendirilen run |
| `faithfulness` | `NUMERIC(4,3)` | ✓ | Yanıtın bağlama sadakati (0.000 – 1.000) |
| `answer_relevancy` | `NUMERIC(4,3)` | ✓ | Yanıtın soruyla ilgililiği (0.000 – 1.000) |
| `context_precision` | `NUMERIC(4,3)` | ✓ | Getirilen bağlamın hassasiyeti (0.000 – 1.000) |
| `overall_score` | `NUMERIC(4,3)` | ✓ | Ağırlıklı ortalama skor |
| `created_at` | `TIMESTAMPTZ` | ✗ | Değerlendirme zamanı, default `NOW()` |

---

### 1.7 `diagnoses`

| Alan | Tip | Nullable | Açıklama |
|------|-----|----------|----------|
| `id` | `UUID` (PK) | ✗ | Benzersiz diagnosis tanımlayıcısı |
| `run_id` | `UUID` (FK → `runs.id`) | ✗ | Teşhis edilen run |
| `root_cause` | `VARCHAR(64)` | ✗ | Kök neden kodu — bkz. not¹ |
| `confidence` | `NUMERIC(4,3)` | ✗ | Teşhis güven skoru (0.000 – 1.000) |
| `evidence` | **`JSONB`** 🔶 | ✓ | Teşhisi destekleyen kanıt objesi `{anomalies, metrics, ...}` |
| `recommendation` | `TEXT` | ✓ | İnsan-okunabilir düzeltme önerisi |
| `created_at` | `TIMESTAMPTZ` | ✗ | Teşhis zamanı, default `NOW()` |

> **Not¹ — `root_cause` değerleri:**
> `stale_document` · `weak_retrieval` · `tool_failure` · `tool_loop` · `cost_spike` · `answer_not_grounded` · `unknown`

---

### 1.8 `alerts`

| Alan | Tip | Nullable | Açıklama |
|------|-----|----------|----------|
| `id` | `UUID` (PK) | ✗ | Benzersiz alert tanımlayıcısı |
| `run_id` | `UUID` (FK → `runs.id`) | ✓ | İlişkili run (sistem geneli alert'lerde `NULL` olabilir) |
| `type` | `VARCHAR(32)` | ✗ | Anomali tipi — bkz. not² |
| `severity` | `VARCHAR(16)` | ✗ | `info` · `warning` · `critical` |
| `message` | `TEXT` | ✗ | Okunabilir uyarı mesajı |
| `created_at` | `TIMESTAMPTZ` | ✗ | Alert oluşturulma zamanı, default `NOW()` |

> **Not² — `type` değerleri (anomali tipleri):**
> `tool_loop` · `tool_failure` · `cost_spike` · `latency_spike` · `stale_data` · `empty_retrieval`

---

## 2. JSONB Alanları Özet Tablosu

Aşağıdaki alanlar PostgreSQL `JSONB` tipinde saklanır ve GIN indeks ile sorgulanabilir.

| Tablo | Alan | Örnek İçerik |
|-------|------|-------------|
| `spans` | `payload` 🔶 | `{"model": "gpt-4", "prompt_tokens": 512, "completion_tokens": 128}` |
| `tool_calls` | `args` 🔶 | `{"query": "istanbul hava durumu", "limit": 5}` |
| `retrievals` | `retrieved_chunks` 🔶 | `[{"text": "...", "score": 0.92, "source": "faq.md"}]` |
| `diagnoses` | `evidence` 🔶 | `{"anomalies": ["tool_loop"], "loop_count": 7, "threshold": 3}` |

> [!IMPORTANT]
> JSONB alanlarına `GIN` indeks eklenmesi önerilir.
> Örnek: `CREATE INDEX ix_spans_payload ON spans USING GIN (payload);`

---

## 3. Tracer API — Pseudocode İmzaları

### 3.1 `@diagent.observe` Decorator

```python
@diagent.observe(agent_name: str = "default")
def observed_function(*args, **kwargs):
    """
    Decorator çalışma akışı (pseudocode):

    1. RUN OLUŞTUR
       run = db.insert(runs, {
           agent_id = get_or_create_agent(agent_name).id,
           input    = serialize(args, kwargs),
           status   = "running",
       })

    2. SPAN'LARI OTOMATİK YAKALA
       with SpanCollector(run_id=run.id):
           # Her LLM çağrısı    → span(type="llm_call")
           # Her tool çağrısı   → span(type="tool_call")
           # Her retrieval      → span(type="retrieval")
           # Sistem olayları    → span(type="system")
           result = original_function(*args, **kwargs)

    3. FINISH ÇAĞIR
       run.output      = serialize(result)
       run.status      = "finished"
       run.duration_ms = elapsed()
       db.update(run)

       # Celery task tetikle → evaluation + anomaly detection + diagnosis
       finish_pipeline.delay(run_id=run.id)

    return result
    """
```

### 3.2 `log_tool_call()` — Yardımcı Fonksiyon

```python
def log_tool_call(
    run_id: UUID,
    tool_name: str,
    args: dict | None = None,       # → JSONB olarak saklanır
    status: str = "success",        # "success" | "error"
    error: str | None = None,
    duration_ms: int | None = None,
) -> UUID:
    """
    tool_calls tablosuna bir kayıt ekler.
    Aynı zamanda aktif SpanCollector varsa type="tool_call" span'ı da oluşturur.

    Returns: oluşturulan tool_call kaydının id'si (UUID)
    """
```

### 3.3 `log_retrieval()` — Yardımcı Fonksiyon

```python
def log_retrieval(
    run_id: UUID,
    query: str,
    retrieved_chunks: list[dict] | None = None,  # → JSONB olarak saklanır
    top_k: int = 5,
    source_age_hours: float | None = None,
) -> UUID:
    """
    retrievals tablosuna bir kayıt ekler.
    Aynı zamanda aktif SpanCollector varsa type="retrieval" span'ı da oluşturur.

    Returns: oluşturulan retrieval kaydının id'si (UUID)
    """
```

---

## 4. Span Tipleri

`spans.type` alanı aşağıdaki 4 değerden birini alır:

| Tip | Açıklama | Tipik `payload` İçeriği |
|-----|----------|------------------------|
| `llm_call` | Bir LLM API çağrısını temsil eder (OpenAI, Ollama vb.) | `{model, prompt_tokens, completion_tokens, temperature, finish_reason}` |
| `tool_call` | Bir harici tool/fonksiyon çağrısını temsil eder | `{tool_name, args, status, error}` |
| `retrieval` | Bir RAG retrieval (vektör arama) işlemini temsil eder | `{query, top_k, chunk_count, avg_score}` |
| `system` | Framework-seviyesi dahili olaylar (routing, planlama vb.) | `{event, detail}` |

> [!NOTE]
> Bir `tool_call` span'ı oluşturulduğunda `tool_calls` tablosuna da ayrı kayıt yazılır.
> Benzer şekilde `retrieval` span'ı oluşturulduğunda `retrievals` tablosuna da ayrı kayıt yazılır.
> Bu sayede hem timeline görünümü (spans) hem de analitik sorgular (tool_calls, retrievals) desteklenir.
