# Cozy Research Agent — Upstash Box + Pydantic AI

Pydantic AI agents running inside Upstash Box containers, with guaranteed delivery via QStash.

## Architecture

```
OpenClaw (VPS)                    Upstash Box (N containers)
  │                                │
  ├─ Cron trigger                  ├─ Python runtime
  │                                ├─ Pydantic AI agent
  ├─ QStash dispatch ───────────►  ├─ Claude Code built-in
  │   (guaranteed delivery)        ├─ Shell / Filesystem
  │                                ├─ Cozy Memory API access
  │                                │
  │  ◄─────────────────────────────┤─ Webhook → QStash
  │   (guaranteed result delivery)  │
  │                                │
  ├─ Cozy Memory (shared)          │
  ├─ Telegram notification         │
```

## How It Works

1. **Dispatch**: OpenClaw cron creates Box instances via QStash
2. **Execute**: Each Box runs a Pydantic AI agent that researches its topic
3. **Research**: Agent uses tools (YouTube, web, Context7 docs) to gather information
4. **Structure**: Pydantic AI enforces structured output (findings, assumptions, recommendations)
5. **Deliver**: Results written to `/work/findings.json`, webhook fires via QStash
6. **Persist**: Webhook handler stores findings in Cozy Memory + sends to Telegram

## Key Features

- **Structured Output**: Pydantic AI `output_type` ensures consistent, typed results
- **Tool Use**: Agent has tools for YouTube, web search, doc lookup, memory recall
- **Durable State**: Box freezes/resumes — agent context persists across sessions
- **Parallel Execution**: Fan-out N topics to N Boxes, collect results via webhooks
- **Guaranteed Delivery**: QStash ensures no results are lost, even on connection drops
- **Shared Memory**: All agents read/write to Cozy Memory (Redis + Vector + libSQL)

## Files

```
research-agent/
├── agent.py              # Pydantic AI agent (runs inside Box)
├── webhook.py            # QStash webhook handler (receives results)
├── src/
│   └── dispatch.ts       # TypeScript dispatcher (creates Boxes)
├── package.json          # Node dependencies
└── README.md
```

## Usage

### Single Research Task

```bash
npx tsx src/dispatch.ts "vLLM KV cache internals"
```

### Parallel Research (fan-out)

```bash
npx tsx src/dispatch.ts --parallel \
  "vLLM KV cache internals" \
  "Triton kernel optimization" \
  "Upstash Workflow durable execution" \
  "Modal GPU memory snapshots"
```

### With QStash Webhook (production)

```bash
# Dispatch with guaranteed delivery
curl -X POST https://qstash.upstash.io/v2/publish \
  -H "Authorization: Bearer $QSTASH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "destination": "https://your-webhook.com/webhook/research",
    "body": {"topic": "vLLM KV cache internals"},
    "retries": 3,
    "callback": "https://your-webhook.com/webhook/research"
  }'
```

## Agent Output Schema

```python
class ResearchResult(BaseModel):
    topic: str                          # What was researched
    summary: str                        # 2-3 paragraph synthesis
    findings: list[ResearchFinding]     # Key findings with confidence scores
    assumptions: list[Assumption]       # Testable claims with verdicts
    recommendations: list[str]          # Actionable next steps
    follow_up_topics: list[str]         # Topics worth researching next
```

## Environment Variables

```bash
# Box
UPSTASH_BOX_API_KEY=abx_xxxxxxxx

# Agent
ANTHROPIC_API_KEY=sk-ant-xxxx        # For Claude Code in Box
OPENAI_API_KEY=sk-xxxx               # For Pydantic AI model

# Cozy Memory (shared context)
UPSTASH_VECTOR_REST_URL=https://...
UPSTASH_VECTOR_REST_TOKEN=...
UPSTASH_REDIS_REST_URL=https://...
UPSTASH_REDIS_REST_TOKEN=...

# QStash (guaranteed delivery)
QSTASH_TOKEN=...
QSTASH_CURRENT_SIGNING_KEY=...
```

## Why This Architecture?

| Component | Role | Why Not Alternative |
|-----------|------|---------------------|
| **Pydantic AI** | Structured decisions + output | Claude Code alone returns free-form text |
| **Upstash Box** | Isolated execution | Modal needs GPU config; no freeze/resume |
| **QStash** | Guaranteed delivery | Direct HTTP can drop messages |
| **Cozy Memory** | Shared context | No shared memory between Boxes otherwise |
| **Zod + Pydantic** | Output validation | TypeScript Zod + Python Pydantic = typed both ways |

## Cost Estimate

- **Box**: ~$0.01-0.05 per research task (10 min, CPU only)
- **QStash**: Free tier (100 msgs/day) or $1/10K msgs
- **Claude Code**: Standard API pricing per token
- **Cozy Memory**: Upstash free tier for most workloads
- **Per daily run** (4 topics parallel): ~$0.05-0.20 total
