"""
Cozy Research Agent — runs inside Upstash Box.

Uses Pydantic AI for structured decision-making and output.
Communicates with Cozy Memory for shared context.
Writes findings to /work/findings.json for Box webhook delivery.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel


# ── Structured Output Models ────────────────────────────────────

class ResearchFinding(BaseModel):
    """A single research finding."""
    topic: str = Field(description="What was researched")
    source: str = Field(description="Where this came from: youtube, web, context7")
    finding: str = Field(description="The actual finding or insight")
    confidence: float = Field(description="Confidence 0.0-1.0", ge=0.0, le=1.0)
    verified: bool = Field(description="Whether verified against official docs")


class Assumption(BaseModel):
    """A testable assumption."""
    assumption: str = Field(description="The claim to verify")
    source: str = Field(description="Where this assumption came from")
    verified: bool = Field(description="Verified against official docs?")
    verdict: str = Field(description="CONFIRMED, DENIED, or PARTIAL")
    evidence: str = Field(description="Evidence for the verdict")


class ResearchResult(BaseModel):
    """Final research output."""
    topic: str = Field(description="The research topic")
    summary: str = Field(description="2-3 paragraph synthesis")
    findings: list[ResearchFinding] = Field(description="Key findings")
    assumptions: list[Assumption] = Field(description="Assumptions tested")
    recommendations: list[str] = Field(description="Actionable recommendations")
    follow_up_topics: list[str] = Field(description="Topics worth researching next")


# ── Dependencies ────────────────────────────────────────────────

class AgentDeps(BaseModel):
    """Dependencies injected into the agent."""
    cozy_memory_url: str = Field(default="")
    cozy_memory_token: str = Field(default="")
    working_dir: str = Field(default="/work")

    class Config:
        arbitrary_types_allowed = True


# ── Agent Definition ───────────────────────────────────────────

model = OpenAIModel(
    model_name=os.environ.get("AGENT_MODEL", "gpt-4o-mini"),
    api_key=os.environ.get("OPENAI_API_KEY", ""),
)

research_agent = Agent(
    model=model,
    deps_type=AgentDeps,
    output_type=ResearchResult,
    system_prompt="""You are a research agent. Your job is to deeply research a topic using available tools.

Process:
1. Understand the research topic
2. Search YouTube for expert explanations and tutorials
3. Search the web for current information and documentation
4. Verify key claims against official documentation
5. Compile findings into structured output

Guidelines:
- Be thorough — make at least 10 searches per topic
- Take everything with a grain of salt — verify against official docs
- Focus on actionable insights, not surface-level summaries
- Note what you couldn't verify or what seems uncertain

You have access to:
- YouTube search and transcript extraction
- Web search (Google AI Mode with citations)
- Official library documentation (Context7)
- Shared memory system for context (Cozy Memory)
""",
)


# ── Tools ───────────────────────────────────────────────────────

@research_agent.tool
async def youtube_search(ctx: RunContext[AgentDeps], query: str) -> str:
    """Search YouTube for videos on a topic. Returns top results with titles and IDs."""
    import subprocess
    result = subprocess.run(
        ["mcporter", "call", "openclaw-youtube.youtube_search", f"q:{query}"],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout[:3000] if result.stdout else "No results"


@research_agent.tool
async def youtube_transcript(ctx: RunContext[AgentDeps], video_id: str) -> str:
    """Extract transcript from a YouTube video."""
    import subprocess
    result = subprocess.run(
        ["mcporter", "call", "openclaw-youtube.youtube_transcript", f"video_id:{video_id}"],
        capture_output=True, text=True, timeout=60
    )
    return result.stdout[:5000] if result.stdout else "No transcript available"


@research_agent.tool
async def web_search(ctx: RunContext[AgentDeps], query: str) -> str:
    """Search the web using Google AI Mode. Returns synthesized answer with citations."""
    import subprocess
    result = subprocess.run(
        ["mcporter", "call", "openclaw-searchtool.google_ai_mode", f"q:{query}"],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout[:3000] if result.stdout else "No results"


@research_agent.tool
async def lookup_docs(ctx: RunContext[AgentDeps], library: str, query: str) -> str:
    """Look up official documentation for a library using Context7."""
    import subprocess
    # First resolve library ID
    resolve = subprocess.run(
        ["mcporter", "call", "context7.resolve-library-id",
         f"libraryName:{library}", f"query:{query}"],
        capture_output=True, text=True, timeout=30
    )
    if resolve.returncode != 0:
        return f"Could not resolve library: {library}"

    # Extract library ID from response
    try:
        resp = json.loads(resolve.stdout)
        lib_id = resp.get("result", [{}])[0].get("libraryId", "")
        if not lib_id:
            return f"No library ID found for {library}"
    except (json.JSONDecodeError, IndexError, KeyError):
        return f"Could not parse library resolution for {library}"

    # Query docs
    docs = subprocess.run(
        ["mcporter", "call", "context7.query-docs",
         f"libraryId:{lib_id}", f"query:{query}"],
        capture_output=True, text=True, timeout=30
    )
    return docs.stdout[:5000] if docs.stdout else "No documentation found"


@research_agent.tool
async def memory_recall(ctx: RunContext[AgentDeps], query: str) -> str:
    """Search shared memory for prior research and context."""
    try:
        import httpx
        # Query Cozy Memory via Vector (semantic search)
        resp = httpx.post(
            f"{ctx.deps.cozy_memory_url}/query",
            headers={"Authorization": f"Bearer {ctx.deps.cozy_memory_token}"},
            json={"data": query, "topK": 5, "includeMetadata": True},
            timeout=10.0
        )
        if resp.status_code == 200:
            results = resp.json().get("result", [])
            return json.dumps([{
                "id": r.get("id"),
                "score": r.get("score"),
                "content": r.get("metadata", {}).get("name", ""),
            } for r in results])
        return "No memory results"
    except Exception as e:
        return f"Memory query failed: {e}"


@research_agent.tool
async def write_notes(ctx: RunContext[AgentDeps], filename: str, content: str) -> str:
    """Write research notes to a file in the working directory."""
    path = Path(ctx.deps.working_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"Wrote {len(content)} bytes to {path}"


# ── Main Entry Point ───────────────────────────────────────────

async def run_research(topic: str) -> ResearchResult:
    """Run research on a topic and return structured results."""
    deps = AgentDeps(
        cozy_memory_url=os.environ.get("UPSTASH_VECTOR_REST_URL", ""),
        cozy_memory_token=os.environ.get("UPSTASH_VECTOR_REST_TOKEN", ""),
        working_dir="/work",
    )

    result = await research_agent.run(
        f"Research the following topic thoroughly: {topic}",
        deps=deps,
    )

    return result.output


def main():
    """CLI entry point. Reads topic from args or /work/topic.txt."""
    if len(sys.argv) > 1:
        topic = " ".join(sys.argv[1:])
    elif Path("/work/topic.txt").exists():
        topic = Path("/work/topic.txt").read_text().strip()
    else:
        print("Usage: python agent.py <topic>", file=sys.stderr)
        sys.exit(1)

    print(f"Researching: {topic}", file=sys.stderr)
    result = asyncio.run(run_research(topic))

    # Write structured output for Box webhook
    output_path = Path("/work/findings.json")
    output_path.write_text(result.model_dump_json(indent=2))
    print(f"Findings written to {output_path}", file=sys.stderr)

    # Also write human-readable summary
    summary_path = Path("/work/summary.md")
    summary_path.write_text(f"# Research: {topic}\n\n{result.summary}\n\n"
                           f"## Recommendations\n" +
                           "\n".join(f"- {r}" for r in result.recommendations) +
                           f"\n\n## Follow-up Topics\n" +
                           "\n".join(f"- {t}" for t in result.follow_up_topics))
    print(f"Summary written to {summary_path}", file=sys.stderr)

    # Print JSON to stdout for Box capture
    print(result.model_dump_json())


if __name__ == "__main__":
    main()
