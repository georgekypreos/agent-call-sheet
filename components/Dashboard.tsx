"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentDTO, AgentsResponse, BucketName } from "@/lib/types";
import { BUCKET_NAMES } from "@/lib/types";
import { fireConfetti } from "./Confetti";
import { openSingleTab } from "./singleTab";
import AgentCard from "./AgentCard";

const BROKERAGE_CHIPS = [
  { tag: "green valley", label: "Green Valley" },
  { tag: "signature real estate group", label: "Signature Real Estate Group" },
  { tag: "southwest", label: "Southwest" },
  { tag: "northwest", label: "Northwest" },
  { tag: "utah", label: "Utah" },
];

type TabKey = "" | BucketName | "coops" | "birthday" | "anniversary";

export default function Dashboard({ topN }: { topN: number }) {
  const [data, setData] = useState<AgentsResponse | null>(null);
  const [tab, setTab] = useState<TabKey>("");
  const [showAll, setShowAll] = useState(false);
  const [activeChips, setActiveChips] = useState<Set<string>>(new Set());
  const [refreshing, setRefreshing] = useState(false);
  const lastCalledRef = useRef(0);
  const confettiFiredRef = useRef(false);

  const load = useCallback(async () => {
    const params = new URLSearchParams();
    params.set("n", String(showAll ? 1000 : topN));
    if (tab) params.set("bucket", tab);
    const r = await fetch("/api/agents?" + params.toString());
    if (!r.ok) return;
    const json = (await r.json()) as AgentsResponse;
    setData(json);
  }, [tab, topN, showAll]);

  useEffect(() => {
    load();
  }, [load]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await fetch("/api/refresh", { method: "POST" });
      await load();
    } finally {
      setRefreshing(false);
    }
  };

  const handleCalled = async (a: AgentDTO) => {
    const wasCalled = a.called;
    let outcome: string | null = null;
    let note = "";
    if (!wasCalled) {
      outcome = window.prompt(
        "Call outcome? (Reached / Left Message / No Answer / Bad Number / Busy)\n— or Cancel to just tag without logging",
        "Reached"
      );
    }
    await fetch(`/api/called/${a.fubId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ called: !wasCalled }),
    });
    if (!wasCalled && outcome) {
      await fetch(`/api/log-call/${a.fubId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outcome, duration_seconds: 300, note }),
      });
    }
    await load();
  };

  const handleBucket = async (a: AgentDTO, target: BucketName) => {
    const newBucket = a.bucket === target ? "" : target;
    await fetch(`/api/bucket/${a.fubId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bucket: newBucket }),
    });
    await load();
  };

  const handleSkip = async (a: AgentDTO) => {
    await fetch(`/api/skip/${a.fubId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skip: !a.skipped }),
    });
    await load();
  };

  const handleSaveNote = async (a: AgentDTO, body: string) => {
    if (!body.trim()) return;
    await fetch(`/api/note/${a.fubId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: body }),
    });
  };

  const toggleChip = (tag: string) => {
    const next = new Set(activeChips);
    if (next.has(tag)) next.delete(tag);
    else next.add(tag);
    setActiveChips(next);
  };

  const filteredAgents = (() => {
    if (!data) return [];
    if (tab === "coops") return data.agents;
    if (activeChips.size === 0) return data.agents;
    return data.agents.filter((a) => {
      const tagsLc = a.tags.map((t) => t.toLowerCase());
      const office = (a.office ?? "").toLowerCase();
      return Array.from(activeChips).some(
        (c) => tagsLc.some((t) => t.includes(c)) || office.includes(c)
      );
    });
  })();

  const calledCount = filteredAgents.filter((a) => a.called).length;
  const denom = Math.min(topN, filteredAgents.length) || 1;
  const pct = denom > 0 ? calledCount / denom : 0;

  // Fire confetti when reaching 100%
  useEffect(() => {
    if (denom > 0 && calledCount >= denom) {
      if (!confettiFiredRef.current) {
        confettiFiredRef.current = true;
        fireConfetti();
      }
    } else {
      confettiFiredRef.current = false;
    }
    lastCalledRef.current = calledCount;
  }, [calledCount, denom]);

  const affirmation = (() => {
    if (denom <= 0) return null;
    const p = pct;
    if (calledCount >= denom) return { text: "Good job! You completed your task today.", klass: "celebrate" };
    if (p >= 0.9) return { text: "Just one more — you've got this!", klass: "encourage" };
    if (p >= 0.75) return { text: "Almost there — final stretch!", klass: "encourage" };
    if (p >= 0.5) return { text: "You're halfway done!", klass: "encourage" };
    if (p >= 0.25) return { text: "Nice start — keep the momentum.", klass: "encourage" };
    if (calledCount === 0) return { text: "Anyone you don't reach today will come back tomorrow — give it your best shot.", klass: "hint" };
    return null;
  })();

  return (
    <>
      {/* Top bar */}
      <header className="flex justify-between items-end gap-4 flex-wrap pb-5 mb-5 border-b border-border/30">
        <div>
          <h1 className="text-[26px] font-bold tracking-tight text-text mb-1">Today's top {topN} calls</h1>
          <p className="text-sm text-muted font-medium">
            {data?.last_sync ? new Date(data.last_sync).toLocaleString() : "Loading…"}
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="px-3.5 py-2 rounded-lg bg-accent text-white font-medium shadow-sm hover:bg-accent-hover disabled:opacity-50"
          >
            {refreshing ? "Refreshing…" : "Refresh data"}
          </button>
          <button
            onClick={() => setShowAll((v) => !v)}
            className="px-3.5 py-2 rounded-lg bg-card border border-border-strong font-medium hover:bg-slate-50"
          >
            {showAll ? `Show top ${topN}` : "Show all"}
          </button>
        </div>
      </header>

      {/* Filter chips */}
      <div className="flex gap-2.5 flex-wrap items-center p-3 bg-card border border-border rounded-xl mb-2.5 shadow-card-sm">
        <span className="font-bold text-text">Brokerage tag:</span>
        {BROKERAGE_CHIPS.map((chip) => {
          const active = activeChips.has(chip.tag);
          return (
            <button
              key={chip.tag}
              onClick={() => toggleChip(chip.tag)}
              className={
                "px-3 py-1.5 rounded-full border text-xs font-medium transition-all " +
                (active
                  ? "bg-accent border-accent text-white shadow-sm"
                  : "bg-card border-border-strong text-text hover:bg-slate-50")
              }
            >
              {chip.label}
            </button>
          );
        })}
        {activeChips.size > 0 && (
          <button onClick={() => setActiveChips(new Set())} className="text-xs text-muted px-2 py-1 hover:text-text">
            Clear
          </button>
        )}
        <div className="flex-1" />
        <span className="text-xs text-muted">
          {data && filteredAgents.length !== data.agents.length
            ? `${filteredAgents.length} of ${data.agents.length} match`
            : data
            ? `${data.agents.length} total`
            : ""}
        </span>
      </div>

      {/* Bucket tabs */}
      <div className="flex gap-2.5 flex-wrap items-center p-3 bg-card border border-border rounded-xl mb-2.5 shadow-card-sm">
        <span className="font-bold text-text">View:</span>
        {(
          [
            ["", "Top ten", null] as const,
            ["coops", "Coops", data?.special_counts.coops ?? 0] as const,
            ["birthday", "🎂 Birthday", data?.special_counts.birthday ?? 0] as const,
            ["anniversary", "🎉 Anniversary", data?.special_counts.anniversary ?? 0] as const,
            ["nurture", "Nurture", data?.buckets_counts.nurture ?? 0] as const,
            ["warm", "Warm", data?.buckets_counts.warm ?? 0] as const,
            ["hot", "Hot", data?.buckets_counts.hot ?? 0] as const,
          ]
        ).map(([key, label, count]) => {
          const active = tab === key;
          return (
            <button
              key={key}
              onClick={() => setTab(key as TabKey)}
              className={
                "px-3.5 py-1.5 rounded-full border text-sm font-medium inline-flex items-center gap-1.5 transition-all " +
                (active
                  ? "bg-accent border-accent text-white shadow-sm"
                  : "bg-card border-border-strong text-text hover:bg-slate-50")
              }
            >
              {label}
              {count !== null && (
                <span
                  className={
                    "text-[11px] font-semibold px-1.5 py-px rounded-full min-w-[18px] text-center " +
                    (active ? "bg-white/20 text-white" : "bg-slate-100 text-muted")
                  }
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Dry-run banner */}
      {data?.dry_run && (
        <div className="bg-warn-bg text-warn p-2.5 px-3.5 rounded-lg mb-3 text-sm">
          Dry-run mode is on. Nothing will be written to Follow Up Boss. Set <code>DRY_RUN=false</code> in environment to enable writes.
        </div>
      )}

      {/* Progress bar (sticky) */}
      <div className="sticky top-0 z-50 bg-bg pb-3 -mx-6 px-6">
        <div className="flex flex-col gap-2 p-3.5 px-4 bg-card border border-border rounded-xl text-sm shadow-card-sm">
          <div className="flex items-center gap-3.5">
            <div className="text-xs font-semibold text-muted tabular-nums whitespace-nowrap">
              {calledCount} of {denom} called
            </div>
            <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-accent to-purple-500 rounded-full transition-[width] duration-300"
                style={{ width: `${Math.round(pct * 100)}%` }}
              />
            </div>
          </div>
          {affirmation && (
            <div
              className={
                "text-sm leading-snug " +
                (affirmation.klass === "celebrate"
                  ? "text-success font-bold bg-success-bg px-2.5 py-1.5 rounded-md border border-emerald-200 self-start"
                  : affirmation.klass === "encourage"
                  ? "text-accent font-semibold"
                  : "text-muted italic")
              }
            >
              {affirmation.text}
            </div>
          )}
        </div>
      </div>

      {/* List */}
      <div className="flex flex-col gap-2.5">
        {filteredAgents.length === 0 && (
          <div className="text-center py-10 text-muted">
            {!data
              ? "Loading agents…"
              : activeChips.size > 0 && data.agents.length > 0
              ? "No agents in the call list match your brokerage filter."
              : data.agents.length === 0 && (data.last_sync === null || data.total === 0)
              ? (
                <>
                  <p className="mb-2">No agents in the database yet.</p>
                  <p className="text-sm">
                    Click <strong>Refresh data</strong> above to pull contacts from FUB and Courted.
                    The first sync takes 30–60 seconds.
                  </p>
                </>
              )
              : "No agents match the current view."}
            {activeChips.size > 0 && data && data.agents.length > 0 && (
              <div className="mt-3.5">
                <button
                  onClick={() => setActiveChips(new Set())}
                  className="px-3.5 py-2 rounded-lg bg-accent text-white font-semibold"
                >
                  Clear filters
                </button>
              </div>
            )}
          </div>
        )}
        {filteredAgents.map((a, i) => {
          // Insert group divider for Top ten tab when group changes from "most" to "least"
          const prev = i > 0 ? filteredAgents[i - 1].group : null;
          const showDivider = a.group && a.group !== prev;
          return (
            <div key={`${a.fubId}-${a.courtedId}`}>
              {showDivider && (
                <div
                  className={
                    "flex items-center gap-3 my-2 text-[11px] font-bold uppercase tracking-wider " +
                    (a.group === "most" ? "text-success" : "text-warn")
                  }
                >
                  <div className="flex-1 h-px bg-border" />
                  <span
                    className={
                      "px-3 py-1 rounded-full border " +
                      (a.group === "most"
                        ? "bg-success-bg border-emerald-200"
                        : "bg-warn-bg border-amber-200")
                    }
                  >
                    {a.group === "most" ? "Top 5 producers — most transactions" : "Bottom 5 — least transactions"}
                  </span>
                  <div className="flex-1 h-px bg-border" />
                </div>
              )}
              <AgentCard
                agent={a}
                onCalled={() => handleCalled(a)}
                onBucket={(b) => handleBucket(a, b)}
                onSkip={() => handleSkip(a)}
                onSaveNote={(note) => handleSaveNote(a, note)}
                onOpenFub={() => a.fub_url && openSingleTab("fub", a.fub_url)}
                onOpenCourted={() => a.courted_url && openSingleTab("courted", a.courted_url)}
              />
            </div>
          );
        })}
      </div>
    </>
  );
}
