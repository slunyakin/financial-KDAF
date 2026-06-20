import { createUIMessageStream, createUIMessageStreamResponse, generateId } from "ai";
import { type NextRequest } from "next/server";

export const runtime = "nodejs";

type PythonEvent =
  | { event: "node_done"; node: string; summary: string }
  | { event: "result"; summary: string }
  | { event: "error"; message: string };

export async function POST(req: NextRequest) {
  const authHeader = req.headers.get("Authorization") ?? "";

  if (!authHeader) {
    return new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 });
  }

  let body: { messages?: Array<{ role: string; content: string | Array<{ type: string; text?: string }> }> };
  try {
    body = await req.json();
  } catch {
    return new Response(JSON.stringify({ detail: "Invalid JSON body" }), { status: 400 });
  }

  const messages = body.messages ?? [];
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  const question =
    typeof lastUser?.content === "string"
      ? lastUser.content
      : (lastUser?.content ?? [])
          .filter((p): p is { type: "text"; text: string } => p.type === "text")
          .map((p) => p.text)
          .join(" ");

  if (!question.trim()) {
    return new Response(JSON.stringify({ detail: "No question provided" }), { status: 400 });
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
        signal: req.signal,
      });

      if (!res.ok || !res.body) {
        writer.write({ type: "error", errorText: `Backend error ${res.status}` });
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let hasResult = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.replace(/\r\n/g, "\n").split("\n\n");
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
            hasResult = true;
            const textId = generateId();
            writer.write({ type: "text-start", id: textId });
            writer.write({ type: "text-delta", id: textId, delta: payload.summary });
            writer.write({ type: "text-end", id: textId });
          } else if (payload.event === "error") {
            writer.write({ type: "error", errorText: payload.message });
          }
        }
      }

      // Flush any remaining bytes from multi-byte UTF-8 sequences
      buffer += decoder.decode();
      // If the backend never emitted a result event, surface an error
      if (!hasResult) {
        writer.write({ type: "error", errorText: "No result received from backend" });
      }
    },
    onError: (err) => (err instanceof Error ? err.message : String(err)),
  });

  return createUIMessageStreamResponse({ stream });
}
