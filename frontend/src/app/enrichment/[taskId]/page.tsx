"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { AssistantChatTransport, useChatRuntime } from "@assistant-ui/react-ai-sdk";
import { Thread } from "@/components/assistant-ui/thread";
import { getTask, getToken, graphWrite, resolveTask, type EnrichmentTask } from "@/lib/api";

// ── write-back panel ──────────────────────────────────────────────────────────

function WriteBackPanel({ taskId, onResolved }: { taskId: string; onResolved: (elementId: string) => void }) {
  const [cypher, setCypher] = useState("");
  const [preview, setPreview] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const res = await graphWrite({ cypher });
      await resolveTask(taskId);
      onResolved(res.element_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">KG Write-back</h2>

      {!preview ? (
        <>
          <textarea
            value={cypher}
            onChange={(e) => setCypher(e.target.value)}
            placeholder="MERGE (r:BusinessRule {id: 'R001'}) SET r.description = '...', r.visibility = ['analyst']"
            rows={8}
            className="w-full bg-muted border border-border rounded-lg px-4 py-3 text-sm font-mono text-foreground placeholder-muted-foreground focus:outline-none focus:border-ring resize-none"
          />
          <button
            onClick={() => setPreview(true)}
            disabled={!cypher.trim()}
            className="self-end px-4 py-2 bg-primary hover:bg-primary/90 text-primary-foreground disabled:opacity-40 disabled:cursor-not-allowed rounded text-sm font-medium transition-colors"
          >
            Preview
          </button>
        </>
      ) : (
        <>
          <div className="bg-muted border border-amber-600/40 rounded-lg px-4 py-3">
            <p className="text-xs text-amber-400 mb-2 font-medium">Review before committing:</p>
            <pre className="text-sm font-mono text-foreground whitespace-pre-wrap break-words">{cypher}</pre>
          </div>

          <div className="flex gap-2 justify-end">
            <button
              onClick={() => setPreview(false)}
              className="px-4 py-2 bg-secondary hover:bg-secondary/80 text-secondary-foreground rounded text-sm font-medium transition-colors"
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

          {error && <p className="text-destructive text-sm">{error}</p>}
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
  const [resolvedElementId, setResolvedElementId] = useState<string | null>(null);
  const [invalidId, setInvalidId] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    if (!/^[\w-]+$/.test(taskId)) {
      setInvalidId(true);
      return;
    }
    getTask(taskId).then(setTask).catch((e: unknown) => {
      setFetchError(e instanceof Error ? e.message : String(e));
    });
  }, [taskId]);

  const transport = useMemo(
    () => new AssistantChatTransport({ api: "/api/chat", headers: () => ({ Authorization: `Bearer ${getToken()}` }) }),
    [],
  );
  const runtime = useChatRuntime({ transport });

  const welcome = task?.question_text
    ? `This gap was triggered by: "${task.question_text}". Ask me what context is missing.`
    : "Ask me about this knowledge gap.";

  const WelcomeMessage = useMemo(
    () => () => (
      <div className="flex flex-col items-center px-4 text-center mb-6">
        <p className="text-muted-foreground text-sm">{welcome}</p>
      </div>
    ),
    [welcome],
  );

  if (invalidId) {
    return (
      <div className="h-screen flex items-center justify-center">
        <p className="text-destructive text-sm">Invalid task ID.</p>
      </div>
    );
  }

  if (fetchError) {
    return (
      <div className="h-screen flex items-center justify-center">
        <p className="text-destructive text-sm">Failed to load task: {fetchError}</p>
      </div>
    );
  }

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="h-screen flex flex-col">
        <div className="shrink-0 border-b border-border px-6 py-4 flex items-center gap-4">
          <button
            onClick={() => router.push("/enrichment")}
            className="text-muted-foreground hover:text-foreground text-sm transition-colors"
          >
            ← Tasks
          </button>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-foreground truncate">
              {task?.question_text ?? decodeURIComponent(taskId)}
            </p>
            <div className="flex gap-3 text-xs text-muted-foreground mt-0.5">
              {task?.source && <span>source: {task.source}</span>}
              {task?.submitted_by && <span>by: {task.submitted_by}</span>}
              {resolved && <span className="text-green-400">resolved</span>}
            </div>
          </div>
        </div>

        <div className="flex-1 min-h-0 grid grid-cols-2 divide-x divide-border">
          <div className="flex flex-col min-h-0">
            <Thread components={{ Welcome: WelcomeMessage }} />
          </div>
          <div className="overflow-y-auto px-6 py-6">
            {resolved ? (
              <p className="text-green-400 text-sm">
                Written — node <code className="font-mono">{resolvedElementId}</code>. Task resolved. Return to the task list.
              </p>
            ) : (
              <WriteBackPanel
                taskId={decodeURIComponent(taskId)}
                onResolved={(id) => { setResolvedElementId(id); setResolved(true); }}
              />
            )}
          </div>
        </div>
      </div>
    </AssistantRuntimeProvider>
  );
}
