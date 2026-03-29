/**
 * Cozy Pipeline — XState state machines derived from Michael's Stately designs.
 *
 * Sources:
 * - spacetimeMachine: Agent orchestration (approve/monitor/track pattern)
 * - searchProcess: Memory recall (cache → semantic → fulltext → return)
 * - videoProduction: Research pipeline (research → produce → publish)
 * - vapiVoiceLayer: Integration architecture (Workflow + Vector + Search + Redis)
 */

import { createMachine, assign } from "xstate";

// ── Types ──────────────────────────────────────────────────────

interface PipelineContext {
  topic: string;
  boxId: string | null;
  findings: Record<string, unknown>[];
  assumptions: Record<string, unknown>[];
  summary: string;
  cost: number;
  error: string | null;
  retryCount: number;
}

interface RecallContext {
  query: string;
  cacheHit: boolean;
  vectorResults: unknown[];
  searchResults: unknown[];
  finalResults: unknown[];
}

// ═══════════════════════════════════════════════════════════════
// 1. Research Pipeline (from: spacetimeMachine + videoProduction)
// ═══════════════════════════════════════════════════════════════

/**
 * State flow (adapted from spacetimeMachine + videoProduction):
 *
 *   idle → dispatchCommand → awaitingBox
 *          awaitingBox → boxReady → agentRunning
 *          agentRunning → collectingResults → storingFindings
 *          storingFindings → notifyingUser → complete
 *
 *   At any point: → error → retry (up to 3) → or → failed
 */
export const researchPipelineMachine = createMachine(
  {
    id: "researchPipeline",
    initial: "idle",
    context: {
      topic: "",
      boxId: null,
      findings: [],
      assumptions: [],
      summary: "",
      cost: 0,
      error: null,
      retryCount: 0,
    } as PipelineContext,
    states: {
      // ── From spacetimeMachine: idle ──
      idle: {
        on: {
          DISPATCH: {
            target: "dispatchingCommand",
            actions: assign({ topic: ({ event }) => event.topic }),
          },
        },
      },

      // ── From spacetimeMachine: issuingCommand ──
      dispatchingCommand: {
        invoke: {
          src: "dispatchToBox",
          input: ({ context }) => ({ topic: context.topic }),
          onDone: {
            target: "awaitingBox",
            actions: assign({ boxId: ({ event }) => event.output.boxId }),
          },
          onError: {
            target: "error",
            actions: assign({ error: ({ event }) => String(event.error) }),
          },
        },
      },

      // ── From spacetimeMachine: awaitingApproval ──
      awaitingBox: {
        invoke: {
          src: "waitForBoxReady",
          input: ({ context }) => ({ boxId: context.boxId }),
          onDone: "agentRunning",
          onError: {
            target: "error",
            actions: assign({ error: ({ event }) => String(event.error) }),
          },
        },
        after: {
          60000: "error", // 60s timeout
        },
      },

      // ── From spacetimeMachine: monitoringAgents ──
      agentRunning: {
        invoke: {
          src: "runPydanticAgent",
          input: ({ context }) => ({
            boxId: context.boxId,
            topic: context.topic,
          }),
          onDone: "collectingResults",
          onError: {
            target: "error",
            actions: assign({ error: ({ event }) => String(event.error) }),
          },
        },
        after: {
          600000: "error", // 10min timeout
        },
      },

      // ── From videoProduction: topic research complete ──
      collectingResults: {
        invoke: {
          src: "readFindings",
          input: ({ context }) => ({ boxId: context.boxId }),
          onDone: {
            target: "storingFindings",
            actions: assign({
              findings: ({ event }) => event.output.findings,
              assumptions: ({ event }) => event.output.assumptions,
              summary: ({ event }) => event.output.summary,
              cost: ({ event }) => event.output.cost,
            }),
          },
          onError: {
            target: "error",
            actions: assign({ error: ({ event }) => String(event.error) }),
          },
        },
      },

      // ── From videoProduction: script written ──
      storingFindings: {
        invoke: {
          src: "storeToMemory",
          input: ({ context }) => ({
            topic: context.topic,
            findings: context.findings,
            summary: context.summary,
          }),
          onDone: "notifyingUser",
          onError: "notifyingUser", // non-blocking — store failure doesn't stop notification
        },
      },

      // ── From videoProduction: post video ──
      notifyingUser: {
        invoke: {
          src: "sendNotification",
          input: ({ context }) => ({
            topic: context.topic,
            summary: context.summary,
            findingsCount: context.findings.length,
            cost: context.cost,
          }),
          onDone: "cleanup",
          onError: "cleanup", // non-blocking
        },
      },

      // ── Cleanup: delete Box ──
      cleanup: {
        invoke: {
          src: "deleteBox",
          input: ({ context }) => ({ boxId: context.boxId }),
          onDone: "complete",
          onError: "complete", // box cleanup failure is non-fatal
        },
      },

      // ── From spacetimeMachine: completeTask ──
      complete: {
        type: "final",
        output: ({ context }) => ({
          topic: context.topic,
          findings: context.findings,
          assumptions: context.assumptions,
          summary: context.summary,
          cost: context.cost,
        }),
      },

      // ── From spacetimeMachine: error handling ──
      error: {
        always: [
          {
            guard: ({ context }) => context.retryCount < 3,
            target: "retrying",
            actions: assign({ retryCount: ({ context }) => context.retryCount + 1 }),
          },
          { target: "failed" },
        ],
      },

      retrying: {
        after: {
          2000: "dispatchingCommand", // 2s backoff then retry
        },
      },

      failed: {
        type: "final",
        output: ({ context }) => ({
          error: context.error,
          topic: context.topic,
          retryCount: context.retryCount,
        }),
      },
    },
  },
  {
    // Services would be provided by the orchestrator
    actors: {
      dispatchToBox: async ({ input }: { input: { topic: string } }) => {
        throw new Error("Not implemented — provide dispatchToBox actor");
      },
      waitForBoxReady: async ({ input }: { input: { boxId: string | null } }) => {
        throw new Error("Not implemented — provide waitForBoxReady actor");
      },
      runPydanticAgent: async ({
        input,
      }: {
        input: { boxId: string | null; topic: string };
      }) => {
        throw new Error("Not implemented — provide runPydanticAgent actor");
      },
      readFindings: async ({ input }: { input: { boxId: string | null } }) => {
        throw new Error("Not implemented — provide readFindings actor");
      },
      storeToMemory: async ({
        input,
      }: {
        input: { topic: string; findings: unknown[]; summary: string };
      }) => {
        throw new Error("Not implemented — provide storeToMemory actor");
      },
      sendNotification: async ({
        input,
      }: {
        input: {
          topic: string;
          summary: string;
          findingsCount: number;
          cost: number;
        };
      }) => {
        throw new Error("Not implemented — provide sendNotification actor");
      },
      deleteBox: async ({ input }: { input: { boxId: string | null } }) => {
        throw new Error("Not implemented — provide deleteBox actor");
      },
    },
  }
);

// ═══════════════════════════════════════════════════════════════
// 2. Memory Recall (from: searchProcess)
// ═══════════════════════════════════════════════════════════════

/**
 * State flow (from searchProcess):
 *
 *   idle → checkCache
 *          cacheHit → returnToUser
 *          cacheMiss → semanticMatch → fullTextSearch → cacheAndAnalytics → returnToUser
 */
export const memoryRecallMachine = createMachine({
  id: "memoryRecall",
  initial: "idle",
  context: {
    query: "",
    cacheHit: false,
    vectorResults: [],
    searchResults: [],
    finalResults: [],
  } as RecallContext,
  states: {
    idle: {
      on: {
        RECALL: {
          target: "checkingCache",
          actions: assign({ query: ({ event }) => event.query }),
        },
      },
    },

    // ── From searchProcess: checkCache ──
    checkingCache: {
      invoke: {
        src: "checkRedisCache",
        input: ({ context }) => ({ query: context.query }),
        onDone: [
          {
            guard: ({ event }) => event.output.hit === true,
            target: "returningToUser",
            actions: assign({
              cacheHit: true,
              finalResults: ({ event }) => event.output.results,
            }),
          },
          {
            target: "semanticSearch",
          },
        ],
        onError: "semanticSearch", // cache failure → fallback to search
      },
    },

    // ── From searchProcess: semanticMatch ──
    semanticSearch: {
      invoke: {
        src: "queryVector",
        input: ({ context }) => ({ query: context.query }),
        onDone: {
          target: "fullTextSearch",
          actions: assign({
            vectorResults: ({ event }) => event.output.results,
          }),
        },
        onError: "fullTextSearch", // vector failure → try fulltext
      },
    },

    // ── From searchProcess: fullTextSearch ──
    fullTextSearch: {
      invoke: {
        src: "querySearch",
        input: ({ context }) => ({ query: context.query }),
        onDone: {
          target: "cachingResults",
          actions: assign({
            searchResults: ({ event }) => event.output.results,
          }),
        },
        onError: "mergingResults", // search failure → use vector results only
      },
    },

    // ── From searchProcess: cacheAndAnalytics ──
    cachingResults: {
      invoke: {
        src: "cacheResults",
        input: ({ context }) => ({
          query: context.query,
          vectorResults: context.vectorResults,
          searchResults: context.searchResults,
        }),
        onDone: "mergingResults",
        onError: "mergingResults", // cache write failure is non-fatal
      },
    },

    mergingResults: {
      entry: assign({
        finalResults: ({ context }) => {
          // Merge vector + search results, deduplicate by ID, sort by score
          const seen = new Map<string, unknown>();
          for (const r of [
            ...context.vectorResults,
            ...context.searchResults,
          ] as { id: string; score: number }[]) {
            if (!seen.has(r.id) || (seen.get(r) as any)?.score < r.score) {
              seen.set(r.id, r);
            }
          }
          return Array.from(seen.values()).sort(
            (a: any, b: any) => b.score - a.score
          );
        },
      }),
      target: "returningToUser",
    },

    // ── From searchProcess: returnToUser ──
    returningToUser: {
      type: "final",
      output: ({ context }) => ({
        results: context.finalResults,
        cacheHit: context.cacheHit,
        sources: {
          vector: context.vectorResults.length,
          search: context.searchResults.length,
        },
      }),
    },
  },
});

// ═══════════════════════════════════════════════════════════════
// 3. Agent Orchestrator (from: spacetimeMachine)
// ═══════════════════════════════════════════════════════════════

/**
 * State flow (from spacetimeMachine):
 *
 *   idle → issueCommand → monitoringAgents → trackingProgress → complete
 *   idle → requestApproval → approve/reject → idle
 *
 * Adapted for: managing multiple Box agents in parallel
 */
export const agentOrchestratorMachine = createMachine({
  id: "agentOrchestrator",
  initial: "idle",
  context: {
    tasks: [] as string[],
    activeAgents: new Map<string, string>(),
    completedAgents: [] as string[],
    results: new Map<string, unknown>(),
  },
  states: {
    idle: {
      on: {
        ORCHESTRATE: {
          target: "issuingCommands",
          actions: assign({
            tasks: ({ event }) => event.topics as string[],
          }),
        },
      },
    },

    issuingCommands: {
      invoke: {
        src: "dispatchParallel",
        input: ({ context }) => ({ topics: context.tasks }),
        onDone: {
          target: "monitoringAgents",
          actions: assign({
            activeAgents: ({ event }) => new Map(Object.entries(event.output)),
          }),
        },
        onError: "idle",
      },
    },

    monitoringAgents: {
      on: {
        AGENT_UPDATE: {
          actions: assign({
            activeAgents: ({ context, event }) => {
              const updated = new Map(context.activeAgents);
              updated.set(event.boxId, event.status);
              return updated;
            },
          }),
        },
        AGENT_COMPLETE: {
          actions: assign({
            completedAgents: ({ context, event }) => [
              ...context.completedAgents,
              event.boxId,
            ],
            results: ({ context, event }) => {
              const updated = new Map(context.results);
              updated.set(event.boxId, event.result);
              return updated;
            },
          }),
        },
      },
      always: {
        guard: ({ context }) =>
          context.completedAgents.length === context.tasks.length,
        target: "collectingResults",
      },
    },

    collectingResults: {
      entry: assign({
        completedAgents: ({ context }) => {
          // Delete all boxes
          for (const boxId of context.activeAgents.keys()) {
            // Fire-and-forget box deletion
          }
          return context.completedAgents;
        },
      }),
      target: "complete",
    },

    complete: {
      type: "final",
      output: ({ context }) => ({
        results: Object.fromEntries(context.results),
        completedCount: context.completedAgents.length,
      }),
    },
  },
});

// ═══════════════════════════════════════════════════════════════
// 4. Integration Map (from: vapiVoiceLayer)
// ═══════════════════════════════════════════════════════════════

/**
 * NOT a runnable state machine — this is an architecture reference
 * showing how components connect (from vapiVoiceLayer):
 *
 *   Request → Router → Sync Path (direct) or Async Path (Workflow)
 *   Both paths: → Redis Session Store → Upstash Vector/Search → Tool Execution → Response
 *
 * For our stack:
 *   Trigger → Router → Sync (direct Box) or Async (QStash → Workflow → Box)
 *   Both paths: → Cozy Memory (Redis + Vector) → Pydantic AI Agent → Results
 */

export const INTEGRATION_ARCHITECTURE = {
  // From vapiVoiceLayer states
  components: {
    entryPoint: "OpenClaw cron or manual trigger",
    router: "Decide sync vs async path",
    syncPath: "Direct Box creation + agent run",
    asyncPath: "QStash → Upstash Workflow → Box",
    memory: {
      redis: "Hot cache, session state, dedup",
      vector: "Semantic search (BGE_LARGE_EN_V1_5)",
      libsql: "Persistent source of truth",
    },
    agent: "Pydantic AI inside Upstash Box",
    output: "QStash webhook → Telegram + Cozy Memory",
  },

  // From vapiVoiceLayer events
  events: {
    process_request: "New research task arrives",
    sync_processing: "Direct execution (Box created immediately)",
    async_processing: "Durable execution (via QStash + Workflow)",
    execute_tool: "Agent invokes YouTube/web/Context7 tool",
    process_workflow: "Workflow step checkpoint",
    next: "Advance to next state/component",
  },
};

console.log("✅ XState machines loaded:");
console.log("  - researchPipelineMachine (from spacetimeMachine + videoProduction)");
console.log("  - memoryRecallMachine (from searchProcess)");
console.log("  - agentOrchestratorMachine (from spacetimeMachine)");
console.log("  - INTEGRATION_ARCHITECTURE (from vapiVoiceLayer)");
