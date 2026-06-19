# ADR-006: Vercel AI SDK UIMessage Stream Protocol for Frontend Streaming

**Status:** Accepted
**Date:** 2026-06-17

## Context

The streaming pipeline (`POST /api/v1/query/stream`) emits a custom SSE format with three event types: `node_done`, `result`, and `error`. The original frontend consumed this via a hand-rolled `ChatModelAdapter` using `useLocalRuntime` from `@assistant-ui/react`.

Problems with that approach:
- Node progress events were rendered as inline markdown (`*[node_name]* summary`) injected into the message body — a hack, not a structured part
- `@assistant-ui/react-ai-sdk` was installed but unused; `thread.tsx` already ships `ToolFallback` and `ToolGroupRoot` components that render tool call parts natively with collapsible UI, timing, and status icons — all dead code
- The adapter accumulated text and yielded the full string on every event (not a streaming delta)
- JWT auth was manually injected inside the adapter's `fetch()` call

The root cause was a missing Next.js BFF route: `useChatRuntime` requires a route that speaks the AI SDK UIMessage stream protocol (v6). Without that route, `useLocalRuntime` + custom adapter was the only option.

## Decision

Add a Next.js route handler at `frontend/src/app/api/chat/route.ts` (the BFF layer) that:

1. Accepts `POST` with the standard AI SDK `{ messages }` body
2. Extracts the Bearer token from the incoming `Authorization` header and forwards it to the Python backend
3. Calls `POST /api/v1/query/stream` on the Python backend (unchanged)
4. Converts Python SSE events to AI SDK v6 UIMessageChunk protocol using `createUIMessageStream` + `createUIMessageStreamResponse` from `ai`:
   - `node_done` → `tool-input-available` (dynamic) + `tool-output-available` (dynamic): each LangGraph node renders as a collapsible step in the Thread UI
   - `result` → `text-start` + `text-delta` + `text-end`
   - `error` → `error` chunk

Replace `useLocalRuntime` + `makeAdapter` in `frontend/src/app/enrichment/[taskId]/page.tsx` with `useChatRuntime({ transport })` where `transport = new AssistantChatTransport({ api: "/api/chat", headers: { Authorization: ... } })` from `@assistant-ui/react-ai-sdk`. The transport is stabilized with `useMemo([], [])` to prevent re-instantiation on every render.

The Python backend (`run_query_stream`, `POST /api/v1/query/stream`) is **unchanged**.

## Mapping: Python SSE → AI SDK UIMessageChunk (v6)

```
node_done (check_cache)    → { type: "tool-input-available",  toolCallId: id, toolName: "check_cache", input: {}, dynamic: true }
                           → { type: "tool-output-available", toolCallId: id, output: "cache miss",    dynamic: true }
node_done (refiner)        → { type: "tool-input-available",  toolCallId: id, toolName: "refiner",     input: {}, dynamic: true }
                           → { type: "tool-output-available", toolCallId: id, output: "3 terms; …",    dynamic: true }
result                     → { type: "text-start", id }
                           → { type: "text-delta", id, delta: "The top 10 products…" }
                           → { type: "text-end",   id }
error                      → { type: "error", errorText: "…" }
```

The Thread's existing `group-tool` renderer collapses all tool call parts into a single `ToolGroupRoot` with a count badge, each expanding to show the node name and result summary via `ToolFallback`.

## Next.js rewrite interaction

`next.config.ts` rewrites `/api/:path*` → Python backend. Next.js filesystem routes (App Router route handlers) take precedence over rewrites, so `/api/chat` is served by the route handler and not proxied.

## Consequences

- Node progress renders as native collapsible tool steps (with spinner while running, checkmark when done, timing) instead of inline markdown strings
- `thread.tsx` tool group and tool fallback components are no longer dead code
- JWT is forwarded server-side via the BFF layer — the `Authorization` header flows: client → Next.js route → Python backend
- `makeAdapter` and ~50 lines of manual SSE parsing are removed from the client
- Python backend is untouched; other callers of `POST /api/v1/query/stream` are unaffected
- Text accumulation bug (yielding full accumulated string per event) is eliminated — the AI SDK handles delta assembly
