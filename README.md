# Cozy Memory 🧶

Unified memory system for AI agents — five backends, one clean interface.

## What Is This?

AI agents need different types of memory at different speeds. Cozy Memory gives you a single `recall()` / `store()` API that automatically picks the right backend:

| Backend | Use Case | Speed |
|---------|----------|-------|
| **Upstash Redis** | Hot cache, session state, queues, rate limiting | ~5ms |
| **Upstash Vector** | Semantic search with built-in BGE embeddings | ~50ms |
| **libSQL** | Local persistence, source of truth, graph relations | Local |
| **Upstash QStash** | Guaranteed message delivery, scheduling, retries | Async |

Think of it like a human brain:
- **Redis** = working memory (what you're thinking about *right now*)
- **Vector** = associative memory ("that reminds me of...")
- **Search** = factual recall ("what was that number?")
- **libSQL** = long-term memory (everything, permanently)

## Install

```bash
pip install -e .

# With libSQL support
pip install -e ".[libsql]"

# Everything
pip install -e ".[all]"
```

## Quick Start

```python
from cozy_memory import CozyMemory, RecallStrategy

# Initialize (reads from environment variables)
mem = CozyMemory()

# ── Recall ───────────────────────────────────────────────

# Auto-selects best backend based on query style
results = mem.recall("What did we decide about KV cache compression?")
# → Vector (semantic search)

results = mem.recall("FP8_kv_cache_dtype")
# → Search (keyword, contains special chars)

results = mem.recall("entity:turboquant")
# → Redis (key lookup)

# Force a specific backend
results = mem.recall("recent work", strategy=RecallStrategy.VECTOR)
results = mem.recall("benchmark results", strategy=RecallStrategy.SEARCH)

# Query everything, merge by score
results = mem.recall("Modal GPU snapshots", strategy=RecallStrategy.AUTO)

# ── Store ────────────────────────────────────────────────

# Store in libSQL (truth) + auto-sync to Vector + Redis
mem.store(
    id="turboquant",
    type="project",
    name="TurboQuant Triton Kernel",
    description="MSE-only 3-bit KV cache compression with Triton block GEMM",
    metadata={"status": "active", "cos_sim": 0.943},
)

# ── Activity Tracking ────────────────────────────────────

mem.log_activity("research_complete", {"topic": "vLLM KV cache"})
recent = mem.recent_activity(count=10)

# ── Deduplication ────────────────────────────────────────

# Prevent re-running the same research within 48h
if not mem.already_done("research:vllm-kv-cache"):
    # Do the research...
    pass

# ── Rate Limiting ────────────────────────────────────────

result = mem.rate_limit("youtube-api", limit=10, window=60)
if result["allowed"]:
    # Make the API call...
    pass

# ── Sync ─────────────────────────────────────────────────

# Full sync: libSQL entities → Upstash Vector + Redis cache
stats = mem.sync.sync_all_entities()
# → {"synced": 42, "failed": 0, "total": 42}

# ── Health ───────────────────────────────────────────────

health = mem.health()
# → {"redis": True, "vector": True, "search": True, "libsql": True, "qstash": True}
```

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    CozyMemory.recall()                    │
│                   .store()  .sync()                       │
├──────────┬──────────┬────────────────────────────────────┤
│  Redis   │  Vector  │           libSQL                   │
│          │          │                                    │
│ Hot      │ Semantic │ Persistent                          │
│ cache    │ search   │ storage                             │
│ Queues   │ BGE      │ Graph                               │
│ State    │ embed    │ relations                           │
│ Rate     │ 1024d    │ Source                              │
│ limit    │ auto     │ of truth                            │
├──────────┴──────────┴────────────────────────────────────┤
│                    Upstash QStash                         │
│                                                          │
│  Guaranteed delivery · Auto-retries · Scheduling         │
│  Dead letter queue · Deduplication · Fan-out             │
└──────────────────────────────────────────────────────────┘
         ↕               ↕               ↕
   Sub-agents        Swarm workers    Cron jobs
   Chat bots         Modal agents     Webhooks
```

## Configuration

All config via environment variables:

```bash
# Upstash Redis
UPSTASH_REDIS_REST_URL=https://your-redis.upstash.io
UPSTASH_REDIS_REST_TOKEN=your-token

# Upstash Vector (also used for search via auto-embed)
UPSTASH_VECTOR_REST_URL=https://your-vector.upstash.io
UPSTASH_VECTOR_REST_TOKEN=your-token

# Upstash QStash (guaranteed message delivery)
QSTASH_URL=https://qstash.upstash.io
QSTASH_TOKEN=your-token
QSTASH_SIGNING_KEY=your-signing-key

# libSQL (optional, defaults to ./memory.db)
COZY_LIBSQL_PATH=/path/to/memory.db

# Redis tuning (optional)
COZY_REDIS_PREFIX=cozy:        # Key prefix
COZY_REDIS_TTL=3600            # Default TTL in seconds
```

## Backend Details

### Redis — Hot Cache (~5ms)

Best for: things you need *right now* with sub-second latency.

```python
mem.redis.set("session:abc123", {"user": "michael", "context": "turboquant"})
mem.redis.get("session:abc123")

# Queues
mem.redis.enqueue("research_tasks", {"topic": "vLLM internals"})
task = mem.redis.dequeue("research_tasks")

# Activity log
mem.redis.log_activity("deploy", {"service": "swarm-workers"})
mem.redis.recent_activity(count=10)
```

### Upstash Vector — Semantic Search (~50ms)

Best for: "find things *related* to this concept."

Built-in embedding model: `BGE_LARGE_EN_V1_5` (1024 dimensions). No need to bring your own embeddings.

```python
# Upsert (auto-embeds the data string)
mem.vector.upsert("turboquant", "KV cache compression with 3-bit quantization")

# Semantic search
results = mem.vector.query("How to reduce memory in transformer inference?", top_k=5)
# → Finds "turboquant" even though the words don't match exactly
```

### Upstash Search — Keyword Search (~50ms)

Best for: "find documents containing this exact phrase."

```python
results = mem.search.search("CosSim 0.943", top_k=5)
# → Exact keyword matching
```

### libSQL — Persistent Storage

Best for: long-term storage, graph relations, the source of truth.

```python
# Entities with relations
mem.libsql.upsert_entity("turboquant", "project", "TurboQuant Kernel")
mem.libsql.upsert_entity("triton", "technology", "Triton Lang")
mem.libsql.add_relation("turboquant", "triton", "uses")

# Full-text search (LIKE-based)
entities = mem.libsql.search_entities("compression")
```

## Strategy Selection

When `strategy=AUTO` (default), Cozy Memory picks the backend based on query heuristics:

| Query Pattern | Strategy | Why |
|--------------|----------|-----|
| `entity:key` or short with `:` | Redis | Looks like a key lookup |
| Contains `"quotes"` or `_` `-` `.` | Search | Looks like exact/technical term |
| Everything else | Vector | Default semantic search |
| Fallback | All merged | If primary returns nothing |

You can always override with `strategy=RecallStrategy.VECTOR` etc.

### QStash — Guaranteed Delivery

Best for: messages that must arrive, even if connections drop.

```python
# Publish with guaranteed delivery
mem.qstash.publish_json(
    url="https://your-webhook.com/results",
    data={"topic": "vLLM", "findings": "..."},
    retries=3,  # auto-retry up to 3 times
)

# Delayed delivery
mem.qstash.publish(
    url="https://your-endpoint.com/remind",
    body="Check research status",
    delay=3600,  # deliver in 1 hour
)

# Deduplicated delivery (won't send same ID twice)
mem.qstash.publish_json(
    url="https://your-endpoint.com/callback",
    data={"result": "..."},
    dedup_id=mem.qstash.make_dedup_id("research", "vllm", "2026-03-29"),
)

# Scheduled (cron)
mem.qstash.schedule(
    url="https://your-endpoint.com/daily",
    body={"task": "daily-research"},
    cron="0 3 * * *",  # daily at 3 AM
)
```

## Use Cases

### AI Agent Memory

```python
# Sub-agent starts, loads context
mem = CozyMemory()
context = mem.recall("What was I working on yesterday?")
# → Pulls from Vector (semantic) + Redis (recent activity)

# Sub-agent completes, stores results
mem.store("research:vllm-2026-03-28", type="research", description="...")
mem.log_activity("research_complete", {"topic": "vLLM"})
```

### Deduplication

```python
# Before spawning a research sub-agent
if mem.already_done("research:topic-x", ttl=86400):
    print("Already researched this in the last 24h, skipping")
```

### Cross-Session Continuity

```python
# Cron job at 3 AM needs context from yesterday's conversation
mem = CozyMemory()
prior_work = mem.recall("Modal GPU snapshot issues", top_k=10)
# → Finds relevant entities from Vector + Search + libSQL
```

## Sync Flow

```
libSQL (source of truth)
  │
  ├─→ Vector (upsert for semantic search)
  │     └─ auto-embeds via BGE_LARGE_EN_V1_5
  │
  ├─→ Search (index for keyword search)
  │
  └─→ Redis (cache for fast lookups)
        └─ 24h TTL, auto-refresh on access
```

Call `mem.sync.sync_all_entities()` to push everything from libSQL to the cloud backends.

## Box Templates

The `box-templates/` directory contains ready-to-use scripts for running AI agents inside [Box](https://box.com) serverless environments (Upstash's Python sandbox):

### `box-templates/research-agent/`

End-to-end patterns for Box-based research agents:

| File | Purpose |
|------|---------|
| `agent.py` | Main Pydantic AI research agent (runs inside Box) |
| `pipeline.ts` | Full E2E pipeline: trigger → Box → results |
| `box-connect.mjs` | Connect to and inspect existing Box instances |
| `create-snapshot.ts` | Save a configured Box environment as a reusable snapshot |
| `test-box.ts` | Quick smoke test — create a Box, run code, verify output |
| `test-box2.ts` | Extended test scenarios for Box API patterns |
| `test-fresh.ts` | Test a fresh Box environment from scratch |
| `test-list.mjs` | List all running Box instances |
| `test-snapshot.ts` | Test snapshot creation and restore |
| `practice.mjs` / `practice2.mjs` | Exploratory scripts for learning Box patterns |
| `cleanup-boxes.ts` | Terminate all running Box instances (cost cleanup) |
| `webhook.py` | Webhook receiver for Box result callbacks |

**Quick start:**
```bash
cd box-templates/research-agent
npm install
npx ts-node test-box.ts
```

**Requirements:** Set `OPENROUTER_API_KEY` and Box API credentials in your environment.

## License

MIT
