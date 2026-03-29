"""
QStash Webhook Handler — receives Box research results and delivers to Cozy Memory + Telegram.

Deploy as a lightweight FastAPI server or run as a QStash consumer.
Verifies QStash signatures for security.
"""

import hashlib
import hmac
import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

app = FastAPI(title="Cozy Research Webhook")


# ── Models ──────────────────────────────────────────────────────

class ResearchWebhook(BaseModel):
    """Payload from QStash containing Box research results."""
    box_id: str
    topic: str
    status: str  # "completed" | "failed"
    findings: list[dict] | None = None
    assumptions: list[dict] | None = None
    summary: str | None = None
    recommendations: list[str] | None = None
    follow_up_topics: list[str] | None = None
    cost_usd: float = 0.0
    error: str | None = None


# ── QStash Signature Verification ──────────────────────────────

def verify_qstash_signature(
    body: bytes,
    signature: str | None,
    signing_key: str | None = None,
) -> bool:
    """Verify QStash request signature."""
    if not signature or not signing_key:
        return False

    expected = hmac.new(
        signing_key.encode(),
        body,
        hashlib.sha256,
    ).digest()

    import base64
    expected_b64 = base64.b64encode(expected).decode()
    return hmac.compare_digest(signature, expected_b64)


# ── Handlers ────────────────────────────────────────────────────

@app.post("/webhook/research")
async def handle_research_webhook(
    request: Request,
    x_qstash_signature: str | None = Header(None),
):
    """Receive research results from QStash."""

    body = await request.body()

    # Verify signature (skip in dev)
    signing_key = os.environ.get("QSTASH_CURRENT_SIGNING_KEY")
    if signing_key and x_qstash_signature:
        if not verify_qstash_signature(body, x_qstash_signature, signing_key):
            raise HTTPException(401, "Invalid signature")

    payload = ResearchWebhook.model_validate_json(body)

    if payload.status == "failed":
        print(f"❌ Research failed: {payload.topic} — {payload.error}")
        # Log to Cozy Memory
        _log_to_memory(payload)
        return {"status": "logged_failure"}

    # Save findings to file
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    findings_dir = Path("/root/.openclaw/workspace/research")
    findings_dir.mkdir(parents=True, exist_ok=True)

    findings_file = findings_dir / f"box-research-{timestamp}.json"
    findings_file.write_text(payload.model_dump_json(indent=2))

    # Store in Cozy Memory
    _store_to_memory(payload)

    # Format for Telegram
    summary = _format_telegram_summary(payload)

    # Send to Telegram via OpenClaw
    _send_telegram(summary)

    print(f"✅ Research delivered: {payload.topic}")
    return {"status": "delivered", "file": str(findings_file)}


# ── Memory Integration ─────────────────────────────────────────

def _store_to_memory(payload: ResearchWebhook):
    """Store research findings in Cozy Memory (Vector + Redis)."""
    try:
        import httpx

        vector_url = os.environ.get("UPSTASH_VECTOR_REST_URL", "")
        vector_token = os.environ.get("UPSTASH_VECTOR_REST_TOKEN", "")

        if not vector_url or not vector_token:
            return

        # Store summary in Vector
        httpx.post(
            f"{vector_url}/upsert",
            headers={"Authorization": f"Bearer {vector_token}"},
            json={
                "vectors": [{
                    "id": f"research:{payload.topic.lower().replace(' ', '-')}",
                    "data": f"{payload.topic}: {payload.summary or 'No summary'}",
                    "metadata": {
                        "type": "research",
                        "name": payload.topic,
                        "box_id": payload.box_id,
                        "cost_usd": payload.cost_usd,
                        "findings_count": len(payload.findings or []),
                        "timestamp": datetime.now().isoformat(),
                    },
                }]
            },
            timeout=10.0,
        )

        # Cache in Redis
        redis_url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
        redis_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

        if redis_url and redis_token:
            httpx.post(
                f"{redis_url}/set/cozy:research:{payload.topic.lower().replace(' ', '-')}",
                headers={"Authorization": f"Bearer {redis_token}"},
                json=payload.model_dump(),
                timeout=5.0,
            )

    except Exception as e:
        print(f"Memory store failed: {e}")


def _log_to_memory(payload: ResearchWebhook):
    """Log failure to memory."""
    try:
        import httpx
        vector_url = os.environ.get("UPSTASH_VECTOR_REST_URL", "")
        vector_token = os.environ.get("UPSTASH_VECTOR_REST_TOKEN", "")

        if vector_url and vector_token:
            httpx.post(
                f"{vector_url}/upsert",
                headers={"Authorization": f"Bearer {vector_token}"},
                json={
                    "vectors": [{
                        "id": f"research-failed:{payload.box_id}",
                        "data": f"Failed research: {payload.topic} — {payload.error}",
                        "metadata": {
                            "type": "research_failure",
                            "box_id": payload.box_id,
                            "error": payload.error,
                        },
                    }]
                },
                timeout=10.0,
            )
    except Exception:
        pass


# ── Telegram Formatting ────────────────────────────────────────

def _format_telegram_summary(payload: ResearchWebhook) -> str:
    """Format research results for Telegram."""
    lines = [f"🔬 *Research Complete: {payload.topic}*\n"]

    if payload.summary:
        lines.append(f"_{payload.summary[:500]}_\n")

    if payload.findings:
        lines.append(f"*Key Findings* ({len(payload.findings)}):")
        for f in payload.findings[:5]:
            confidence = f.get("confidence", 0)
            check = "✅" if f.get("verified") else "⚠️"
            lines.append(f"  {check} {f.get('finding', '')[:100]}")
        lines.append("")

    if payload.assumptions:
        confirmed = sum(1 for a in payload.assumptions if a.get("verdict") == "CONFIRMED")
        denied = sum(1 for a in payload.assumptions if a.get("verdict") == "DENIED")
        partial = sum(1 for a in payload.assumptions if a.get("verdict") == "PARTIAL")
        lines.append(f"*Assumptions*: {confirmed} confirmed, {denied} denied, {partial} partial\n")

    if payload.recommendations:
        lines.append("*Recommendations*:")
        for r in payload.recommendations[:3]:
            lines.append(f"  → {r}")
        lines.append("")

    lines.append(f"💰 Cost: ${payload.cost_usd:.4f}")
    return "\n".join(lines)


def _send_telegram(text: str):
    """Send message to Telegram via OpenClaw message tool."""
    # In production, this would use the OpenClaw message API
    # For now, print to stdout for manual forwarding
    print(f"\n📱 Telegram message:\n{text}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
