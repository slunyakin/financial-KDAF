import { createUIMessageStream, createUIMessageStreamResponse, generateId } from "ai";
import { type NextRequest } from "next/server";

export const runtime = "nodejs";

type PythonEvent =
  | { event: "node_done"; node: string; summary: string; api_version: string }
  | { event: "result"; summary: string; citations: unknown[]; confidence_score: number; cached: boolean; api_version: string }
  | { event: "error"; message: string; api_version: string };

export async function POST(req: NextRequest) {
  const authHeader = req.headers.get("Authorization") ?? "";

  const body = await req.json();
  const messages: Array<{ role: string; content: string | Array<{ type: string; text?: string }> }> =
    body.messages ?? [];

  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  const question =
    typeof lastUser?.content === "string"
      ? lastUser.content
      : (lastUser?.content ?? [])
          .filter((p): p is { type: "text"; text: string } => p.type === "text")
          .map((p) => p.text)
          .join(" ");

  if (!question.trim()) {
    return new Response(JSON.stringify({ error: "No question provided" }), { status: 400 });
  }

  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

  const stream = createUIMessageStream({
    execute: async ({ writer }) => {
      const res = await fetch(`${backendUrl}/api/v1/query/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: authHeader,
        },
        body: JSON.stringify({ question }),
      });

      if (!res.ok || !res.body) {
        writer.write({ type: "error", errorText: `Backend error ${res.status}` });
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let textId: string | null = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";

        for (const chunk of chunks) {
          if (!chunk.startsWith("data: ")) continue;
          let payload: PythonEvent;
          try {
            payload = JSON.parse(chunk.slice(6)) as PythonEvent;
          } catch {
            continue;
          }

          if (payload.event === "node_done") {
            const toolCallId = generateId();
            writer.write({
              type: "tool-input-available",
              toolCallId,
              toolName: payload.node,
              input: {},
              dynamic: true,
            });
            writer.write({
              type: "tool-output-available",
              toolCallId,
              output: payload.summary,
              dynamic: true,
            });
          } else if (payload.event === "result") {
            textId = generateId();
            writer.write({ type: "text-start", id: textId });
            writer.write({ type: "text-delta", id: textId, delta: payload.summary });
            writer.write({ type: "text-end", id: textId });
          } else if (payload.event === "error") {
            writer.write({ type: "error", errorText: payload.message });
          }
        }
      }
    },
    onError: (err) => (err instanceof Error ? err.message : String(err)),
  });

  return createUIMessageStreamResponse({ stream });
}
