# Diagent Integration Guide

Welcome to the Diagent Integration Guide. This document provides a comprehensive, professional resource for developers looking to integrate their AI Agents or RAG (Retrieval-Augmented Generation) pipelines with Diagent.

Diagent is a self-hosted, lightweight observability backend and SDK designed specifically to monitor, analyze, and diagnose AI agent execution. It tracks tool calls, context retrievals, agent runs, and overall latency/cost. Furthermore, it automatically detects execution anomalies and executes LLM-as-a-judge quality evaluations, initiating automated diagnoses for low-performing runs.

---

## Table of Contents
1. [Introduction](#1-introduction)
2. [Architecture Overview](#2-architecture-overview)
3. [Prerequisites & Backend Setup](#3-prerequisites--backend-setup)
4. [SDK Installation & Environment](#4-sdk-installation--environment)
5. [Integration Method 1: `@diagent.observe` Decorator (Recommended)](#5-integration-method-1-diagentobserve-decorator-recommended)
6. [Integration Method 2: `DiagentTracer` Class (Advanced / Manual Control)](#6-integration-method-2-diagenttracer-class-advanced--manual-control)
7. [Integration Method 3: Direct REST API (Direct HTTP)](#7-integration-method-3-direct-rest-api-direct-http)
8. [Integration Scenarios (End-to-End Examples)](#8-integration-scenarios-end-to-end-examples)
9. [Automated Analysis Pipeline](#9-automated-analysis-pipeline)
10. [Configuration Reference](#10-configuration-reference)
11. [Developing Custom Adapters](#11-developing-custom-adapters)
12. [Troubleshooting](#12-troubleshooting)
13. [Glossary](#13-glossary)

---

## 1. Introduction

When running AI agents in production, systems can easily fail silently. An agent might return a successful `200 OK` HTTP status code while internally repeating tool invocations in an infinite loop, consuming excessive API credits, retrieving outdated or empty context documents, or outputting ungrounded answers.

Diagent addresses these observability challenges by answering three core questions:
1. **What did the agent do?** (Detailed span, tool call, and retrieval trace tracking)
2. **Did it go well?** (Rule-based anomaly detection and LLM-as-a-judge RAG quality scoring)
3. **Why did it break?** (A read-only LangGraph-based Diagnostician Agent that aggregates evidence and provides root-cause analysis)

To cater to different system architectures, Diagent provides three integration tiers:
* **Decorator-based (`@diagent.observe`)**: The recommended path for standard Python applications. It wraps function execution, manages trace context automatically, and handles success/error statuses.
* **Tracer-based (`DiagentTracer`)**: An advanced, manual-control class designed for queue workers, batch jobs, async pipelines, or environments where decorator-based context propagation is difficult.
* **Direct REST API**: A language-agnostic HTTP approach allowing non-Python systems (e.g., Node.js, Go, Java, Rust) to log telemetry directly to Diagent.

---

## 2. Architecture Overview

Diagent is split into a **Client-Side SDK** and a **Server-Side Observability Backend**:

* **Client SDK**: A lightweight, dependency-free wrapper (requiring only `httpx`) that communicates with the backend solely via REST. It has no direct database or queue dependencies.
* **Server Backend**: A FastAPI service connected to a PostgreSQL database (telemetry storage) and a Redis-backed Celery worker pool (asynchronous analysis pipeline).

### System Data Flow

```mermaid
sequenceDiagram
    autonumber
    participant App as Your System (SDK)
    participant API as Diagent FastAPI
    participant DB as PostgreSQL
    participant Worker as Celery Worker (Redis)
    participant Judge as Judge LLM (OpenAI/Ollama)

    App->>API: POST /runs (create run)
    API-->>App: Return run_id
    Note over App: Agent executes its steps...
    App->>API: POST /runs/{id}/retrievals (log document lookup)
    App->>API: POST /runs/{id}/tool_calls (log tool usage)
    App->>API: POST /runs/{id}/spans (log general LLM calls/steps)
    App->>API: POST /runs/{id}/finish (complete run)
    API-->>App: Return run details

    Note over API: Trigger async pipeline
    API->>Worker: Enqueue run_anomaly_detection
    API->>Worker: Enqueue run_rag_evaluation (if retrievals exist)
    
    critical Run Anomaly Detection
        Worker->>DB: Read run, spans, tool calls, retrievals
        Worker->>Worker: Apply 6 rule-based detectors
        Worker->>DB: Write triggered alerts
    end

    critical Run RAG Evaluation
        Worker->>DB: Read retrieval query, chunks & final output
        Worker->>Judge: Send evaluation prompts (faithfulness, relevancy, precision)
        Judge-->>Worker: Return scores [0.0 - 1.0]
        Worker->>DB: Write evaluation scores
    end

    alt RAG Score < Threshold AND Anomaly Alerts Triggered
        Worker->>Worker: Enqueue run_diagnosis
        critical Run Diagnosis (LangGraph)
            Worker->>DB: Gather evidence (run details, alerts, evaluations)
            Worker->>Judge: Send evidence for root-cause reasoning
            Judge-->>Worker: Return diagnosis (root_cause, confidence, recommendation)
            Worker->>DB: Write diagnosis
        end
    end
```

### Database Schema Summary

The backend manages telemetry across 8 primary relational tables:
1. `agents`: Registers agents by name and version.
2. `runs`: Records individual executions (input, output, status, overall duration, token usage, cost).
3. `spans`: Tracks spans of types `llm_call`, `tool_call`, `retrieval`, or `system`.
4. `tool_calls`: Logged tools, parameters, status (success/error), error traces, and duration.
5. `retrievals`: Queries, retrieved text chunks, top_k parameters, and source data age.
6. `evaluations`: Evaluated quality scores (faithfulness, answer relevancy, context precision, overall score).
7. `diagnoses`: Automated diagnostic reports mapping to specific root causes (e.g., `stale_document`, `weak_retrieval`, `tool_failure`).
8. `alerts`: Anomaly alerts generated by the rule-based detector service.

---

## 3. Prerequisites & Backend Setup

### System Requirements
* Docker and Docker Compose
* Git
* Python 3.10+ (for running Python SDK integrations)

### Step-by-Step Setup
1. **Clone the Repository:**
   ```bash
   git clone <your-diagent-repo-url>
   cd Diagent
   ```

2. **Configure Environment Variables:**
   Copy the example environment file and open it to configure your settings:
   ```bash
   cp .env.example .env
   ```
   Provide your OpenAI API key or set up Ollama details:
   ```ini
   # For OpenAI Judge
   DIAGENT_JUDGE_BACKEND=openai
   OPENAI_API_KEY=your-openai-api-key-here
   OPENAI_JUDGE_MODEL=gpt-4o-mini

   # Or for Ollama (Local)
   # DIAGENT_JUDGE_BACKEND=ollama
   # OLLAMA_BASE_URL=http://host.docker.internal:11434
   # OLLAMA_JUDGE_MODEL=llama3.1
   ```

3. **Start the Docker Services:**
   Spin up the PostgreSQL database, Redis instance, FastAPI app, and Celery worker:
   ```bash
   docker compose up -d --build
   ```

4. **Verify Backend Liveness:**
   Send a request to the healthcheck endpoint:
   ```bash
   curl http://localhost:8000/healthz
   ```
   **Expected Response:**
   ```json
   {"status": "ok", "version": "0.1.0"}
   ```

> [!CAUTION]
> **Security Warning:** Diagent API does not implement built-in authentication or authorization mechanisms. You must deploy it within a secure private network, behind a virtual private network (VPN), or protect it using a reverse proxy (e.g., Nginx, Apache) with Basic/Bearer Auth. **Do not expose the Diagent API directly to the public internet.**

---

## 4. SDK Installation & Environment

Diagent is structured as a monorepo. The client SDK is located in the `diagent/core/tracer.py` module and depends only on `httpx`.

### Adding SDK to your Project
Since the repository is not currently distributed via PyPI, you can install the SDK locally in editable mode (recommended) or reference the repository directory manually.

#### Method A: Local Editable Installation (Recommended)
This is the cleanest and most professional way to install the SDK in your environment. It registers the local `diagent` package to your active Python environment so that you can import it normally, while allowing any changes in the SDK files to take effect immediately.

Run the following command from the root of the cloned Diagent repository:
```bash
pip install -e .
```
Or, if you are installing it from another directory or project context:
```bash
pip install -e /path/to/cloned/Diagent
```

#### Method B: Environment Variable `PYTHONPATH` (Fallback)
Alternatively, you can export the cloned repository path to your `PYTHONPATH` environment variable:
```bash
export PYTHONPATH="/path/to/Diagent:$PYTHONPATH"
```
In a Dockerfile, you can set it like this:
```dockerfile
ENV PYTHONPATH=/app/Diagent:$PYTHONPATH
```

#### Method C: Dynamic `sys.path` Modifying (Fallback)
If you cannot configure the environment or install the package, you can add the path programmatically at the very top of your application entrypoint:
```python
import sys
sys.path.insert(0, "/absolute/path/to/Diagent")

import diagent
```

### SDK Dependencies
If installing via **Method A**, dependencies (like `httpx`) are resolved and installed automatically.
If using manual folder referencing (**Method B** or **Method C**), ensure your environment has `httpx` installed:
```bash
pip install httpx>=0.27.0
```

### SDK Environment Variable
The tracer uses the `DIAGENT_API_URL` environment variable to determine where the backend is running. If not specified, it defaults to `http://localhost:8000`.
```bash
export DIAGENT_API_URL="http://localhost:8000"
```

---

## 5. Integration Method 1: `@diagent.observe` Decorator (Recommended)

The `@observe` decorator wraps an execution function, creating a `run` record on the server, injecting context variables to track nested calls, capturing runtime errors, and finalizing the run.

### Basic Usage
```python
import diagent

@diagent.observe(agent_name="customer-support-bot")
def handle_customer_query(question: str) -> str:
    # Under the hood, this creates a run with 'question' as input.
    answer = f"Hello! You asked: '{question}'. How can I assist you today?"
    
    # Return value is automatically captured as the run output.
    return answer
```

### Context-Aware Helper Functions
When a function is decorated with `@observe`, you can call helper functions inside it. These helpers read the current run context automatically and dispatch HTTP telemetry to Diagent.

#### 1. Logging Retrievals: `diagent.log_retrieval`
Use this function right after fetching documents from a Vector Database or search engine.
```python
diagent.log_retrieval(
    query="refund policy duration",
    retrieved_chunks=[
        {
            "text": "Customers can request a refund within 14 days of purchase.",
            "source": "faq_refunds.md",
            "score": 0.95
        },
        {
            "text": "Refund processing takes 3-5 business days to clear.",
            "source": "billing_policy.md",
            "score": 0.82
        }
    ],
    top_k=5,
    source_age_hours=24.0
)
```
* **`query`** (str): The search query used.
* **`retrieved_chunks`** (list[dict]): Extracted documents. Each chunk dictionary should ideally contain `text`, `source`, and optionally `score`.
* **`top_k`** (int): Number of requested documents.
* **`source_age_hours`** (float, optional): Age of the data source. If it exceeds `STALE_DATA_HOURS` (default 72.0), a `stale_data` alert is triggered. If `retrieved_chunks` is empty or null, an `empty_retrieval` alert is triggered.

#### 2. Logging Tool Calls: `diagent.log_tool_call`
Use this function whenever your agent executes a tool or external function.
```python
diagent.log_tool_call(
    tool_name="fetch_user_order",
    args={"order_id": "ORD-99812"},
    status="success", # "success" or "error"
    error=None, # String representation of the error if status is "error"
    duration_ms=280
)
```
* **`status`**: If set to `"error"`, this counts towards the tool error rate. If the error rate for a run meets or exceeds `TOOL_FAILURE_RATE` (default 50%), a `tool_failure` alert is generated.
* **Loop Detection**: If the same `tool_name` is logged $\ge$ `TOOL_LOOP_THRESHOLD` (default 3) times during a single run, a `tool_loop` alert is triggered.

#### 3. Logging Spans: `diagent.log_span`
Use this to track custom internal spans (such as LLM completion APIs, system processing steps, or embedding calls).
```python
from datetime import datetime, timezone

started_at = datetime.now(timezone.utc)
# ... perform LLM API Call ...
ended_at = datetime.now(timezone.utc)

diagent.log_span(
    span_type="llm_call", # "llm_call" | "tool_call" | "retrieval" | "system"
    name="openai-gpt-4o-completion",
    started_at=started_at,
    ended_at=ended_at,
    duration_ms=1450,
    payload={
        "model": "gpt-4o",
        "temperature": 0.0,
        "prompt": "Summarize user request..."
    }
)
```

#### 4. Setting Metadata: `diagent.set_run_metadata`
Accumulate token counts and execution costs during agent execution.
```python
# Accumulate 250 tokens and $0.0015 cost
diagent.set_run_metadata(total_tokens=250, cost_usd=0.0015)

# If you call it again, it adds to the current totals
diagent.set_run_metadata(total_tokens=100, cost_usd=0.0005)
# Totals will now be: 350 tokens, $0.0020 cost.
```
* **Cost Tracking**: If the total `cost_usd` is greater than the average cost of completed runs for this agent by a factor of `COST_SPIKE_MULTIPLIER` (default 5.0), a `cost_spike` alert is triggered.

### Async Function Support
The `@observe` decorator detects asynchronous functions (`async def`) automatically and resolves the trace context correctly.
```python
@diagent.observe(agent_name="async-retriever-agent")
async def run_async_agent(question: str) -> str:
    # Async context is handled automatically.
    # diagent.log_retrieval() or diagent.log_tool_call() can still be called safely.
    return "Async response"
```
*(Note: `diagent.aobserve` is provided as an alias for backward compatibility.)*

### SDK Error Handling
If the decorated function throws an exception, the SDK catches the error, updates the run's state to `status="failed"`, logs the error message to the run record, and re-raises the exception.
If the Diagent API backend is offline, the SDK's internal HTTP calls will raise `httpx.HTTPError`. It is recommended to let these bubbles up or wrap your outer application with fallbacks if you want to ensure your main agent does not crash when the observability backend is down.

---

## 6. Integration Method 2: `DiagentTracer` Class (Advanced / Manual Control)

In environments such as Celery tasks, MQ listeners, streaming loops, or framework-managed pipelines, managing execution context using Python decorators may fail or clash. 

In these cases, instantiate and use the `DiagentTracer` class directly to control the run lifecycle manually by passing the `run_id` explicitly.

### Dynamic Instantiation
```python
from diagent.core.tracer import DiagentTracer

# Instantiates client. Reads base_url from DIAGENT_API_URL env variable if not provided.
tracer = DiagentTracer(base_url="http://localhost:8000", timeout=30.0)
```

### Manual Run Lifecycle Example
```python
import time
from datetime import datetime, timezone
from diagent.core.tracer import DiagentTracer

tracer = DiagentTracer()

try:
    # 1. Initialize the Run
    run_id = tracer.create_run(
        agent_name="manual-invoice-pipeline",
        input_text="Generate invoice for user USR-881"
    )
    print(f"Started manual trace run: {run_id}")

    # 2. Log a retrieval step
    tracer.log_retrieval(
        run_id=run_id,
        query="invoice template USR-881",
        retrieved_chunks=[{"text": "Invoice templates standard...", "source": "templates.db"}],
        top_k=1,
        source_age_hours=2.0
    )

    # 3. Log a tool execution
    t0 = time.perf_counter()
    # ... call billing service tool ...
    duration = int((time.perf_counter() - t0) * 1000)

    tracer.log_tool_call(
        run_id=run_id,
        tool_name="billing_service_charge",
        args={"user": "USR-881", "amount": 49.99},
        status="success",
        duration_ms=duration
    )

    # 4. Finish the Run
    tracer.finish_run(
        run_id=run_id,
        output="Invoice INV-9901 successfully generated.",
        status="finished",
        total_tokens=420,
        cost_usd=0.0012
    )

finally:
    # Always close the tracer's internal HTTP client to release connections
    tracer.close()
```

### Decorator vs. `DiagentTracer` Comparison

| Feature | `@diagent.observe` Decorator | `DiagentTracer` Manual Class |
| :--- | :--- | :--- |
| **Lifecycle Control** | Automatic (starts on call, finishes on return) | Manual (`create_run` and `finish_run`) |
| **Context Propagation** | Implicit (using Python `ContextVar`) | Explicit (must pass `run_id` to each call) |
| **Error Handling** | Auto-captures exceptions & fails run | Manual catch/fail reporting required |
| **Async Support** | Automatic detection | Sync HTTP client (run execution must manage async tasks) |
| **Ideal For** | Standard Python functions, agents, wrappers | Background workers, non-standard framework lifecycles |

---

## 7. Integration Method 3: Direct REST API (Direct HTTP)

For architectures built on non-Python runtimes (Node.js, Go, Rust, Java, etc.) or systems running without the Python SDK, telemetry can be logged directly using standard HTTP calls to the Diagent REST API.

### Direct REST API Sequence

```mermaid
graph TD
    A[Start Run] -->|POST /runs| B(Receive run_id)
    B -->|POST /runs/{run_id}/retrievals| C[Log Retrievals]
    B -->|POST /runs/{run_id}/tool_calls| D[Log Tool Calls]
    B -->|POST /runs/{run_id}/spans| E[Log Spans]
    C & D & E -->|POST /runs/{run_id}/finish| F[Finish Run & Trigger Analysis]
```

### REST Endpoints Specification

#### 1. Start Run (`POST /runs`)
Creates a new run record with `status="running"`.
* **Request Route**: `POST http://localhost:8000/runs`
* **JSON Body**:
  ```json
  {
    "agent_name": "inventory-coordinator",
    "input": "Check stock for item ITEM-554"
  }
  ```
* **Response (201 Created)**:
  ```json
  {
    "id": "761a6b0c-99fa-45d2-b6ab-1d9c7bb7410c",
    "agent_id": "aa1f298c-8f43-41bb-bf23-889ccb222d10",
    "input": "Check stock for item ITEM-554",
    "output": null,
    "status": "running",
    "error": null,
    "duration_ms": null,
    "total_tokens": null,
    "cost_usd": null,
    "created_at": "2026-06-30T18:00:00Z"
  }
  ```

#### 2. Log Retrieval (`POST /runs/{run_id}/retrievals`)
Logs document lookups. Under the hood, this endpoint also creates a companion span with `type="retrieval"` and `duration_ms=0`.
* **Request Route**: `POST http://localhost:8000/runs/761a6b0c-99fa-45d2-b6ab-1d9c7bb7410c/retrievals`
* **JSON Body**:
  ```json
  {
    "query": "ITEM-554 inventory",
    "retrieved_chunks": [
      {
        "text": "ITEM-554: 12 units in stock at Warehouse A.",
        "source": "warehouse_a.json"
      }
    ],
    "top_k": 5,
    "source_age_hours": 1.5
  }
  ```
* **Response (201 Created)**:
  ```json
  {
    "id": "e0a4f5b2-7c1a-4d7a-b219-c889de32f05a",
    "run_id": "761a6b0c-99fa-45d2-b6ab-1d9c7bb7410c",
    "query": "ITEM-554 inventory",
    "retrieved_chunks": [{"text": "ITEM-554: 12 units in stock at Warehouse A.", "source": "warehouse_a.json"}],
    "top_k": 5,
    "source_age_hours": 1.50
  }
  ```

#### 3. Log Tool Call (`POST /runs/{run_id}/tool_calls`)
Logs tool usage. Under the hood, this also creates a companion span with `type="tool_call"` with a start timestamp inferred from the `duration_ms`.
* **Request Route**: `POST http://localhost:8000/runs/761a6b0c-99fa-45d2-b6ab-1d9c7bb7410c/tool_calls`
* **JSON Body**:
  ```json
  {
    "tool_name": "query_warehouse_database",
    "args": {
      "item_id": "ITEM-554"
    },
    "status": "success",
    "error": null,
    "duration_ms": 320
  }
  ```
* **Response (201 Created)**:
  ```json
  {
    "id": "b8a876c1-ff0a-4a6c-9cde-9a818bbbc11a",
    "run_id": "761a6b0c-99fa-45d2-b6ab-1d9c7bb7410c",
    "tool_name": "query_warehouse_database",
    "args": {"item_id": "ITEM-554"},
    "status": "success",
    "error": null,
    "duration_ms": 320
  }
  ```

#### 4. Log General Span (`POST /runs/{run_id}/spans`)
Used for general process logging, such as internal code steps or LLM call completions.
* **Request Route**: `POST http://localhost:8000/runs/761a6b0c-99fa-45d2-b6ab-1d9c7bb7410c/spans`
* **JSON Body**:
  ```json
  {
    "type": "llm_call",
    "name": "local-llama-inference",
    "started_at": "2026-06-30T17:59:58Z",
    "ended_at": "2026-06-30T18:00:00Z",
    "duration_ms": 2000,
    "payload": {
      "temperature": 0.2,
      "max_tokens": 150
    }
  }
  ```
* **Response (201 Created)**:
  ```json
  {
    "id": "18c1b2c3-9def-4a2b-8a8b-18a09a80b80c",
    "run_id": "761a6b0c-99fa-45d2-b6ab-1d9c7bb7410c",
    "type": "llm_call",
    "name": "local-llama-inference",
    "started_at": "2026-06-30T17:59:58Z",
    "ended_at": "2026-06-30T18:00:00Z",
    "duration_ms": 2000,
    "payload": {"temperature": 0.2, "max_tokens": 150}
  }
  ```

#### 5. Finish Run (`POST /runs/{run_id}/finish`)
Completes the run record, calculates final duration, and initiates the asynchronous analysis pipeline on the Celery workers.
* **Request Route**: `POST http://localhost:8000/runs/761a6b0c-99fa-45d2-b6ab-1d9c7bb7410c/finish`
* **JSON Body**:
  ```json
  {
    "output": "We currently have 12 units of ITEM-554 in stock at Warehouse A.",
    "status": "finished",
    "error": null,
    "total_tokens": 180,
    "cost_usd": 0.00036
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "id": "761a6b0c-99fa-45d2-b6ab-1d9c7bb7410c",
    "agent_id": "aa1f298c-8f43-41bb-bf23-889ccb222d10",
    "input": "Check stock for item ITEM-554",
    "output": "We currently have 12 units of ITEM-554 in stock at Warehouse A.",
    "status": "finished",
    "error": null,
    "duration_ms": 2850,
    "total_tokens": 180,
    "cost_usd": 0.00036,
    "created_at": "2026-06-30T18:00:00Z",
    "evaluation": null
  }
  ```

---

## 8. Integration Scenarios (End-to-End Examples)

These Python scenarios illustrate how to integrate common application structures.

### Scenario A: Tool-Calling Agent (Using API-based LLM)
This scenario demonstrates tracking tool executions, capturing failures, and recording API dollar costs.

```python
import time
import diagent

# A mock tool function
def query_payment_gateway(user_id: str) -> dict:
    t0 = time.perf_counter()
    try:
        # Simulate API call
        time.sleep(0.15)
        # return mock result
        result = {"status": "active", "card_brand": "visa"}
        diagent.log_tool_call(
            tool_name="payment_gateway_lookup",
            args={"user_id": user_id},
            status="success",
            duration_ms=int((time.perf_counter() - t0) * 1000)
        )
        return result
    except Exception as e:
        diagent.log_tool_call(
            tool_name="payment_gateway_lookup",
            args={"user_id": user_id},
            status="error",
            error=str(e),
            duration_ms=int((time.perf_counter() - t0) * 1000)
        )
        raise

@diagent.observe(agent_name="payment-verifier-agent")
def verify_payment_status(user_id: str) -> str:
    # 1. Execute tool call (which is traced)
    payment_info = query_payment_gateway(user_id)
    
    # 2. Assume LLM processes this result. We track API cost and tokens.
    # LLM completion costs $0.0025 USD and uses 500 tokens
    diagent.set_run_metadata(total_tokens=500, cost_usd=0.0025)
    
    return f"User payment status is {payment_info['status']}."

# Test the execution
if __name__ == "__main__":
    import os
    os.environ["DIAGENT_API_URL"] = "http://localhost:8000"
    output = verify_payment_status("user_99812")
    print(f"Agent Finished. Output: {output}")
```

### Scenario B: Pure RAG Pipeline (No Agent Logic)
Ideal for standard Search-and-Generate pipelines. There are no tools here, but RAG evaluations and document staleness checks will be performed.

```python
import diagent

def retrieve_docs(query: str) -> list[dict]:
    # Mock retrieval from VectorDB
    chunks = [
        {"text": "Premium subscription costs $19/month.", "source": "pricing.pdf"},
        {"text": "Basic subscription costs $9/month.", "source": "pricing.pdf"}
    ]
    diagent.log_retrieval(
        query=query,
        retrieved_chunks=chunks,
        top_k=2,
        source_age_hours=12.0 # 12 hours old
    )
    return chunks

@diagent.observe(agent_name="rag-pricing-pipeline")
def answer_pricing_question(question: str) -> str:
    # 1. Retrieve
    chunks = retrieve_docs(question)
    
    # 2. Generate answer (Mock)
    answer = "Premium is $19/month and Basic is $9/month."
    
    # 3. Log LLM generation tokens
    diagent.set_run_metadata(total_tokens=150, cost_usd=0.0003)
    
    return answer

if __name__ == "__main__":
    output = answer_pricing_question("How much is the subscription?")
    print(f"RAG Pipeline Finished. Output: {output}")
```

### Scenario C: Hybrid System (Agent + RAG)
A comprehensive agent that fetches documents and also runs stateful tools.

```python
import time
import diagent

def search_knowledge_base(query: str):
    chunks = [{"text": "Refunds are processed within 14 days.", "source": "policy.md"}]
    diagent.log_retrieval(query=query, retrieved_chunks=chunks, top_k=1, source_age_hours=48.0)
    return chunks

def trigger_refund_system(user_id: str, amount: float):
    t0 = time.perf_counter()
    # Simulate a loop anomaly if called repeatedly, or failure if down
    diagent.log_tool_call(
        tool_name="refund_trigger_tool",
        args={"user_id": user_id, "amount": amount},
        status="success",
        duration_ms=int((time.perf_counter() - t0) * 1000)
    )

@diagent.observe(agent_name="hybrid-support-officer")
def process_refund_request(user_id: str, question: str) -> str:
    # Step 1: Retrieval
    docs = search_knowledge_base(question)
    
    # Step 2: Tool operation
    trigger_refund_system(user_id, 49.99)
    
    # Step 3: LLM interaction metadata
    diagent.set_run_metadata(total_tokens=650, cost_usd=0.0042)
    
    return "Your refund request of $49.99 has been approved and is being processed."

if __name__ == "__main__":
    output = process_refund_request("USR-77", "Can I get a refund for my subscription?")
    print(f"Hybrid Agent Finished. Output: {output}")
```

### Scenario D: Self-Hosted / Local Model System
When using self-hosted LLMs (e.g., Llama 3 via Ollama), API dollar-costs are typically zero or not tracked. This example ignores cost tracking and relies on latency spike thresholds.

```python
import time
import diagent

@diagent.observe(agent_name="local-llama-agent")
def run_local_agent(prompt: str) -> str:
    # 1. Retrieve knowledge
    chunks = [{"text": "Local model context chunk", "source": "local_docs.txt"}]
    diagent.log_retrieval(query=prompt, retrieved_chunks=chunks, top_k=1, source_age_hours=2.0)
    
    # 2. Run local LLM inference (simulate heavy workload)
    t0 = time.perf_counter()
    time.sleep(1.8) # Simulate 1.8 seconds processing time
    inference_duration_ms = int((time.perf_counter() - t0) * 1000)
    
    # Log the LLM call as a Span
    diagent.log_span(
        span_type="llm_call",
        name="ollama-llama3.1-inference",
        started_at=None,
        ended_at=None,
        duration_ms=inference_duration_ms,
        payload={"model": "llama3.1", "device": "cuda:0"}
    )
    
    # Note: We DO NOT call set_run_metadata(cost_usd=...) because cost is not applicable.
    # Anomaly detection will skip cost_spike checks or compare against 0.
    # We rely on LATENCY_SPIKE_MS (e.g. if duration exceeds 30000ms).
    
    return "Response generated by local llama."

if __name__ == "__main__":
    output = run_local_agent("Hello local model!")
    print(f"Local Agent Finished. Output: {output}")
```

---

## 9. Automated Analysis Pipeline

When a run is completed (via `POST /runs/{id}/finish`), Diagent pushes the run ID into Redis. Celery workers immediately start the evaluation pipeline.

```
                  [ Run Finish API ]
                          │
                  (Enqueues Tasks)
                          │
         ┌────────────────┴────────────────┐
         ▼                                 ▼
[ Anomaly Detection ]            [ RAG Evaluation ] (if retrievals exist)
  - 6 Rule Detectors               - LLM Judge metrics
  - Writes to `alerts`             - Writes to `evaluations`
         │                                 │
         └────────────────┬────────────────┘
                          │
                 (Checks eligibility)
                          │
                          ▼
                 [ Diagnostician ] (LangGraph)
                   - Gathers evidence & alerts
                   - Formulates root cause
                   - Writes to `diagnoses`
```

### 1. Rule-Based Anomaly Detectors
The worker scans the database tables and tests the run against 6 predefined rules. If any rule triggers, a record is added to the `alerts` table.

| Detector Function | Alert Type | Severity | Environment Key | Default Threshold | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `detect_tool_loop` | `tool_loop` | `warning` | `TOOL_LOOP_THRESHOLD` | `3` | Triggers if the same tool is invoked $\ge$ $N$ times. |
| `detect_tool_failure` | `tool_failure` | `critical` | `TOOL_FAILURE_RATE` | `0.5` | Triggers if tool failures exceed $50\%$ of calls. |
| `detect_cost_spike` | `cost_spike` | `warning` | `COST_SPIKE_MULTIPLIER` | `5.0` | Triggers if cost exceeds average run cost by $5\times$. |
| `detect_latency_spike` | `latency_spike` | `warning` | `LATENCY_SPIKE_MS` | `30000` | Triggers if overall execution takes $> 30$ seconds. |
| `detect_stale_data` | `stale_data` | `warning` | `STALE_DATA_HOURS` | `72.0` | Triggers if a retrieval chunk age exceeds $72$ hours. |
| `detect_empty_retrieval`| `empty_retrieval`| `warning` | N/A | Immediate | Triggers if `retrieved_chunks` is empty (`[]`) or null. |

### 2. RAG Quality Evaluation (LLM-as-a-Judge)
If the run contains logged retrieval operations, the pipeline utilizes a Judge LLM (OpenAI or Ollama) to score RAG performance. It generates three metrics from $0.0$ to $1.0$:
* **Faithfulness**: Is the answer derived *only* from the retrieved context? (Measures hallucination)
* **Answer Relevancy**: Does the answer address the initial user query? (Measures alignment)
* **Context Precision**: Were relevant chunks ranked higher in the retrieved chunk list? (Measures search quality)
* **Overall Score**: The simple average of the three metrics.

### 3. Diagnostician Agent (LangGraph)
If RAG quality is poor (overall score $<$ `DIAGNOSIS_RAG_SCORE_THRESHOLD`, default `0.6`), the worker checks if the run qualifies for automated diagnosis.
* **Trigger Conditions**:
  * Overall RAG score is low ($< 0.6$).
  * **AND** either:
    * **0 Alerts** are triggered (RAG is bad but rules caught nothing, suggesting an *unknown* issue).
    * **2+ Alerts** are triggered (multiple conflicting issues exist, requiring reasoning to determine the true root cause).
  * *(Note: If exactly 1 alert is triggered, diagnosis is skipped because the cause is clear.)*

* **Diagnostic Output**:
  The LangGraph agent uses a 2-node graph (`gather_evidence` $\rightarrow$ `reason`) to generate a JSON report containing:
  * **`root_cause`**: Classified as `stale_document`, `weak_retrieval`, `tool_failure`, `tool_loop`, `cost_spike`, `answer_not_grounded`, or `unknown`.
  * **`confidence`**: Floating point score $[0.0 - 1.0]$.
  * **`evidence`**: Bullet points citing specific spans, database records, or metrics.
  * **`recommendation`**: Human-readable action items for fixing the issue.

---

## 10. Configuration Reference

Diagent reads all configuration options from your `.env` file via Pydantic settings.

### Docker Ports Configuration
* `API_PORT` (default `8000`): Port mapped to access the FastAPI backend.
* `POSTGRES_PORT` (default `15432`): Exposed PostgreSQL database port.
* `REDIS_PORT` (default `16379`): Exposed Redis container port.

### Connection Settings
* `DATABASE_URL` (default `postgresql+asyncpg://diagent:diagent@postgres:5432/diagent`): Async database connection string.
* `REDIS_URL` (default `redis://redis:6379/0`): Redis connection string.
* `DIAGENT_API_URL` (default `http://localhost:8000`): Host/IP of the Diagent API, accessed by SDK tracers.

### Judge LLM Configurations
* `DIAGENT_JUDGE_BACKEND` (default `openai`): Options: `openai` or `ollama`.
* `JUDGE_RATE_LIMIT_SECONDS` (default `1.0`): Pause interval between LLM calls to avoid hitting rate limits.
* `OPENAI_API_KEY`: Required if using the `openai` judge.
* `OPENAI_JUDGE_MODEL` (default `gpt-4o-mini`): OpenAI model used for scoring.
* `OPENAI_BASE_URL` (default `https://api.openai.com/v1`): Custom OpenAI-compatible endpoint.
* `OLLAMA_BASE_URL` (default `http://host.docker.internal:11434`): Base URL for Ollama instances.
* `OLLAMA_JUDGE_MODEL` (default `llama3.1`): Local model used for evaluations.

### Anomaly Thresholds
* `TOOL_LOOP_THRESHOLD` (default `3`): Max duplicate tool calls allowed.
* `TOOL_FAILURE_RATE` (default `0.5`): Max tool failure rate allowed before critical alert.
* `COST_SPIKE_MULTIPLIER` (default `5.0`): Cost multiplier compared to historical agent runs.
* `LATENCY_SPIKE_MS` (default `30000`): Max runtime allowed before latency warning.
* `STALE_DATA_HOURS` (default `72.0`): Max age allowed for document chunks.
* `DIAGNOSIS_RAG_SCORE_THRESHOLD` (default `0.6`): RAG score threshold below which automated diagnostics are triggered.

---

### Domain-Specific Rules and Expected Behavior

Diagent provides general observability primitives such as runs, spans, tool calls, retrievals, alerts, evaluations, and diagnoses. However, every AI agent or RAG system may also have its own domain-specific behavior rules.

For example, in some systems:

* A `chat` route should not execute a vision detection tool.
* A `rag` route should perform at least one retrieval before generating a grounded answer.
* A `vision` or `detect` route should not run object detection unless an image is available.
* A payment tool should not run when the user only asked an informational question.
* A destructive tool should require an explicit user confirmation step.
* A final answer should be consistent with the tools or documents actually used during the run.

Diagent cannot automatically know these project-specific rules unless the integrating system provides them. Therefore, when building a custom adapter, developers should define the expected behavior of their own system and compare it with the actual behavior observed during execution.

A useful pattern is to record both expected and actual behavior:

```json
{
  "intent": "chat",
  "route": "chat",
  "expected_tools": [],
  "actual_tools": ["vision.detect"],
  "violation": "unexpected_tool_for_route"
}
```

This kind of information can be logged as a custom span, alert, or adapter-level diagnostic signal. It allows Diagent and the diagnosis pipeline to understand not only what happened, but also whether it was logically valid for that specific application.

The more precisely a system defines its own intent, route, tool, retrieval, and fallback rules, the more accurately Diagent can help detect invalid behavior, explain failures, and support root-cause analysis.

In short:

* Diagent records and analyzes execution data.
* The integrating application defines what “correct behavior” means for its own domain.
* Custom adapters should bridge this gap by sending both execution traces and domain-specific expectations.


---

## 11. Developing Custom Adapters

For projects that require custom tracing architectures, you can create a custom adapter directly inside the Diagent codebase under the `diagent/adapters/` directory.

### Structural Rules
1. **Separation of Concerns**: Code in the core directory (`diagent/core/`) must remain framework-agnostic. It should never import from `diagent/adapters/` or contain code specific to a particular adapter.
2. **Adapter Isolation**: Place all adapter-specific code, data transformations, mock tools, and configuration handling inside your adapter directory.

### Directory Structure
```
diagent/
└── adapters/
    └── your_custom_adapter/
        ├── __init__.py      # Package definitions & initialization
        └── agent.py         # Entrypoint containing @observe decorations
```

### Steps to Implement an Adapter
1. **Create the Directory**:
   Create a new package subdirectory in `diagent/adapters/`.
2. **Define the Entrypoint**:
   Implement your agent logic in `agent.py` and decorate the main execution function using `@observe`.
3. **Log Run Contexts**:
   Utilize the tracer helper functions (`log_tool_call()`, `log_retrieval()`, `set_run_metadata()`) inside your adapter pipeline.
4. **Referencing Existing Adapters**:
   Check the `diagent/adapters/demo_support_bot/` package for a complete reference implementation demonstrating tool call simulations, retrievals, and token/cost accumulation.

---

## 12. Troubleshooting

### 1. `ConnectionRefusedError` or `HTTP Connection Error`
* **Symptom**: SDK trace attempts crash with connection errors.
* **Resolution**: Verify that the Diagent FastAPI container is running (`docker compose ps`). Check your environment variable settings:
  ```bash
  echo $DIAGENT_API_URL
  ```
  Ensure it matches the address of your running FastAPI service (e.g., `http://localhost:8000` or `http://api:8000` inside internal Docker networks).

### 2. `RuntimeError: No active run`
* **Symptom**: Calling `log_retrieval()`, `log_tool_call()`, or `log_span()` raises a runtime error stating that no active run was found.
* **Cause**: These helper functions use context variables and must be executed within a thread/task wrapped by the `@observe` decorator.
* **Resolution**:
  1. Wrap the calling function with the `@observe` decorator.
  2. If a decorator cannot be used, instantiate `DiagentTracer` manually and pass the `run_id` explicitly (see [Section 6](#6-integration-method-2-diagenttracer-class-advanced--manual-control)).

### 3. `RAG evaluations are not running`
* **Symptom**: Completed runs show `evaluation: null` in database queries.
* **Resolution**:
  * Ensure the run logged at least one retrieval operation via `log_retrieval()` before finalizing.
  * Verify that the run finalized with `status="finished"`. RAG evaluations are skipped for runs that end with `status="failed"`.
  * Check the Celery worker container logs for errors using `docker compose logs worker`.

### 4. `Diagnosis is not being triggered`
* **Symptom**: Low RAG scores are recorded, but no diagnosis is present in the `diagnoses` table.
* **Cause**: The automated diagnostician runs only under specific trigger conditions.
* **Resolution**:
  * Verify the overall evaluation score is below `DIAGNOSIS_RAG_SCORE_THRESHOLD` (default 0.6).
  * Check the alert count for the run. If exactly 1 alert is triggered, diagnosis is skipped (as the issue is clear). Diagnosis runs only for 0 alerts (unknown cause) or 2+ alerts (complex cause).

---

## 13. Glossary

* **Run**: A single, complete execution cycle of an agent or pipeline.
* **Span**: A tracked interval representing an operation within a run (types: `llm_call`, `tool_call`, `retrieval`, `system`).
* **Tool Call**: An execution trace logged when an agent invokes an external function or utility.
* **Retrieval**: An execution trace logged when an agent queries documents or chunks from an index.
* **Evaluation**: An LLM-driven quality scoring report measuring faithfulness, answer relevancy, and context precision.
* **Diagnosis**: A LangGraph-driven report explaining why a run returned poor RAG metrics or triggered multiple alerts.
* **Alert**: A record indicating that a run triggered one of the rule-based anomaly detectors.
