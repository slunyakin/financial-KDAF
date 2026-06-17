"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchTasks, type EnrichmentTask } from "@/lib/api";

type Filter = "open" | "resolved" | "all";

export default function EnrichmentPage() {
  const [tasks, setTasks] = useState<EnrichmentTask[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<Filter>("open");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchTasks(filter)
      .then((r) => { setTasks(r.items); setTotal(r.total); })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [filter]);

  return (
    <div className="max-w-5xl mx-auto px-6 py-10">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Enrichment Tasks</h1>
          <p className="text-gray-400 text-sm mt-1">{total} task{total !== 1 ? "s" : ""} total</p>
        </div>
        <div className="flex gap-2">
          {(["open", "resolved", "all"] as Filter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                filter === f
                  ? "bg-indigo-600 text-white"
                  : "bg-gray-800 text-gray-300 hover:bg-gray-700"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {loading && <p className="text-gray-500">Loading…</p>}
      {error && <p className="text-red-400 text-sm">Error: {error}</p>}
      {!loading && !error && tasks.length === 0 && (
        <p className="text-gray-500">No {filter} tasks.</p>
      )}

      <ul className="space-y-3">
        {tasks.map((task) => (
          <li key={task.task_id}>
            <Link
              href={`/enrichment/${encodeURIComponent(task.task_id)}`}
              className="block bg-gray-900 border border-gray-800 rounded-lg px-5 py-4 hover:border-indigo-500 transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                <p className="text-sm text-gray-100 leading-relaxed line-clamp-2">
                  {task.question_text || "(no question text)"}
                </p>
                <span className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${
                  task.status === "open"
                    ? "bg-amber-900/60 text-amber-300"
                    : "bg-green-900/60 text-green-300"
                }`}>
                  {task.status}
                </span>
              </div>
              <div className="mt-2 flex gap-4 text-xs text-gray-500">
                <span>source: {task.source}</span>
                {task.submitted_by && <span>by: {task.submitted_by}</span>}
                {task.confidence_score != null && (
                  <span>confidence: {(task.confidence_score * 100).toFixed(0)}%</span>
                )}
                {task.created_at && (
                  <span>{new Date(task.created_at).toLocaleDateString()}</span>
                )}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
