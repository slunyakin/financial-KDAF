"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { Thread } from "@assistant-ui/react";
import { getToken, graphWrite, resolveTask, type EnrichmentTask } from "@/lib/api";

// ── backend chat adapter ──────────────────────────────────────────────────────

const makeAdapter = (): ChatModelAdapter => ({
  async *run({ messages, abortSignal }) {
    const last = messages.at(-1);
    const question = last?.content
      .filter((p): p is { type: "text"; text: string } => p.type === "text")
      .map((p) => p.text)
      .join(" ") ?? "";

    const res = await fetch("/api/v1/query/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getToken()}`,
      },
      body: JSON.stringify({ question }),
      signal: abortSignal,
    });

    if (!res.ok || !res.body) throw new Error(`Stream error ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = JSON.parse(line.slice(6));
        if (payload.event === "result") {
          yield { content: [{ type: "text", text: payload.summary }] };
        } else if (payload.event === "node_done" && payload.summary) {
          yield { content: [{ type: "text", text: `*[${payload.node}]* ${payload.summary}\n` }] };
        } else if (payload.event === "error") {
          yield { content: [{ type: "text", text: `Error: ${payload.message}` }] };
        }
      }
    }
  },
});

// ── write-back panel ──────────────────────────────────────────────────────────

function WriteBackPanel({ taskId, onResolved }: { taskId: string; onResolved: () => void }) {
  const [cypher, setCypher] = useState("");
  const [preview, setPreview] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const res = await graphWrite({ cypher });
      setResult(res.element_id);
      await resolveTask(taskId);
      onResolved();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">KG Write-back</h2>

      {!preview ? (
        <>
          <textarea
            value={cypher}
            onChange={(e) => setCypher(e.target.value)}
            placeholder="MERGE (r:BusinessRule {id: 'R001'}) SET r.description = '...', r.visibility = ['analyst']"
            rows={8}
            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-sm font-mono text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500 resize-none"
          />
          <button
            onClick={() => setPreview(true)}
            disabled={!cypher.trim()}
            className="self-end px-4 py-2 bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40 disabled:cursor-not-allowed rounded text-sm font-medium transition-colors"
          >
            Preview
          </button>
        </>
      ) : (
        <>
          <div className="bg-gray-900 border border-amber-600/40 rounded-lg px-4 py-3">
            <p className="text-xs text-amber-400 mb-2 font-medium">Review before committing:</p>
            <pre className="text-sm font-mono text-gray-100 whitespace-pre-wrap break-words">{cypher}</pre>
          </div>

          {result ? (
            <p className="text-green-400 text-sm">
              Written — node <code className="font-mono">{result}</code>. Task resolved.
            </p>
          ) : (
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setPreview(false)}
                className="px-4 py-2 bg-gray-800 hover:bg-gray-700 rounded text-sm font-medium transition-colors"
              >
                Edit
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="px-4 py-2 bg-green-700 hover:bg-green-600 disabled:opacity-40 disabled:cursor-not-allowed rounded text-sm font-medium transition-colors"
              >
                {submitting ? "Committing…" : "Commit to KG"}
              </button>
            </div>
          )}

          {error && <p className="text-red-400 text-sm">{error}</p>}
        </>
      )}
    </div>
  );
}

// ── main page ─────────────────────────────────────────────────────────────────

export default function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const router = useRouter();
  const [task, setTask] = useState<EnrichmentTask | null>(null);
  const [resolved, setResolved] = useState(false);

  useEffect(() => {
    fetch(`/api/v1/enrichment/tasks?status=all&limit=200`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
      .then((r) => r.json())
      .then((data) => {
        const decoded = decodeURIComponent(taskId);
        const found = data.items?.find(
          (t: EnrichmentTask) => t.task_id === decoded || t.task_id === taskId
        );
        if (found) setTask(found);
      })
      .catch(console.error);
  }, [taskId]);

  const adapterRef = useRef(makeAdapter());
  const runtime = useLocalRuntime(adapterRef.current);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="h-screen flex flex-col">
        <div className="shrink-0 border-b border-gray-800 px-6 py-4 flex items-center gap-4">
          <button
            onClick={() => router.push("/enrichment")}
            className="text-gray-400 hover:text-gray-100 text-sm transition-colors"
          >
            ← Tasks
          </button>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-gray-100 truncate">
              {task?.question_text ?? decodeURIComponent(taskId)}
            </p>
            <div className="flex gap-3 text-xs text-gray-500 mt-0.5">
              {task?.source && <span>source: {task.source}</span>}
              {task?.submitted_by && <span>by: {task.submitted_by}</span>}
              {resolved && <span className="text-green-400">resolved</span>}
            </div>
          </div>
        </div>

        <div className="flex-1 min-h-0 grid grid-cols-2 divide-x divide-gray-800">
          <div className="flex flex-col min-h-0">
            <Thread
              welcome={{
                message: task?.question_text
                  ? `This gap was triggered by: "${task.question_text}". Ask me what context is missing.`
                  : "Ask me about this knowledge gap.",
              }}
            />
          </div>
          <div className="overflow-y-auto px-6 py-6">
            {resolved ? (
              <p className="text-green-400 text-sm">Task resolved. Return to the task list.</p>
            ) : (
              <WriteBackPanel taskId={decodeURIComponent(taskId)} onResolved={() => setResolved(true)} />
            )}
          </div>
        </div>
      </div>
    </AssistantRuntimeProvider>
  );
}
