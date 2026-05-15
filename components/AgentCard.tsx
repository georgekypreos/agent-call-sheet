"use client";

import { useState } from "react";
import type { AgentDTO, BucketName } from "@/lib/types";
import { displayName, fmtAnniversary, fmtDate, fmtMoney, fmtTrend, initials } from "./format";

interface Props {
  agent: AgentDTO;
  onCalled: () => void;
  onBucket: (b: BucketName) => void;
  onSkip: () => void;
  onSaveNote: (body: string) => void;
  onOpenFub: () => void;
  onOpenCourted: () => void;
}

const BUCKET_BUTTONS: Array<{ key: BucketName; label: string; on: string }> = [
  { key: "warm", label: "Warm", on: "bg-amber-500 border-amber-500 text-white" },
  { key: "nurture", label: "Nurture", on: "bg-cyan-500 border-cyan-500 text-white" },
  { key: "hot", label: "Hot", on: "bg-rose-500 border-rose-500 text-white" },
];

export default function AgentCard({ agent: a, onCalled, onBucket, onSkip, onSaveNote, onOpenFub, onOpenCourted }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [noteText, setNoteText] = useState("");

  return (
    <div
      className={
        "bg-card border rounded-xl overflow-hidden shadow-card-sm transition-all " +
        (a.called ? "opacity-50 " : "") +
        (a.skipped ? "opacity-70 bg-slate-50 " : "") +
        "border-border hover:border-accent/40 hover:shadow-card-lg"
      }
    >
      {/* Main row */}
      <div className="grid grid-cols-[32px_56px_1fr_auto] gap-3.5 items-center p-4 px-[18px]">
        <div className="text-sm font-semibold text-hint text-right tabular-nums">{a.rank}</div>

        {a.photo ? (
          <img
            src={a.photo}
            alt=""
            className="w-14 h-14 rounded-full object-cover border border-border"
            onError={(e) => {
              const el = e.currentTarget;
              el.replaceWith(
                Object.assign(document.createElement("div"), {
                  className:
                    "w-14 h-14 rounded-full bg-gradient-to-br from-indigo-50 to-violet-100 flex items-center justify-center text-base font-semibold text-accent border border-border",
                  textContent: initials(a),
                })
              );
            }}
          />
        ) : (
          <div className="w-14 h-14 rounded-full bg-gradient-to-br from-indigo-50 to-violet-100 flex items-center justify-center text-base font-semibold text-accent border border-border">
            {initials(a)}
          </div>
        )}

        <div className="min-w-0">
          <p className="text-[15px] font-bold m-0 text-text">
            {displayName(a)}
            {a.bucket && <BucketBadge bucket={a.bucket} />}
            {a.skipped && (
              <span className="ml-2 text-[10px] uppercase tracking-wider font-semibold text-muted bg-slate-100 border border-border px-2 py-0.5 rounded-full">
                Skipped today
              </span>
            )}
            {a.birthday_today && (
              <span className="ml-2 text-[11px] font-bold text-orange-700 bg-gradient-to-r from-amber-100 to-pink-100 border border-amber-300 px-2 py-0.5 rounded-full">
                🎂 Birthday today
              </span>
            )}
            {a.anniversary_today && (
              <span className="ml-2 text-[11px] font-bold text-orange-700 bg-gradient-to-r from-amber-100 to-pink-100 border border-amber-300 px-2 py-0.5 rounded-full">
                🎉 Anniversary today
              </span>
            )}
          </p>
          <p className="text-xs text-muted mt-0.5 mb-1.5">{a.office || ""}</p>
          <div className="flex gap-1 flex-wrap">
            {a.ready_to_move && <Badge color="success">Ready to move</Badge>}
            {a.trouble_at_office && <Badge color="danger">Trouble at office</Badge>}
            {a.decreasing_sales && <Badge color="warn">Decreasing sales</Badge>}
            {a.fresh_talent && <Badge color="info">Fresh talent</Badge>}
            {a.predicted_growth && <Badge color="pink">Predicted growth</Badge>}
          </div>
        </div>

        <div className="text-right min-w-[110px]">
          <div className="text-[17px] font-bold tabular-nums text-text">{fmtMoney(a.ltm_sales_volume)}</div>
          <div className="text-[11px] text-muted mt-0.5">
            {a.ltm_closed_units} deals · {a.active_listings + a.pending_listings} active/pending
          </div>
        </div>
      </div>

      {/* Controls row */}
      <div className="flex gap-2 px-[18px] pb-3.5 flex-wrap items-center pl-[110px]">
        <div className="flex gap-1.5 text-xs">
          {a.phone && (
            <a
              href={`tel:${a.phone}`}
              className="text-accent bg-accent-bg px-2.5 py-1 rounded-md font-medium hover:bg-accent-soft"
            >
              📞 Call {a.phone}
            </a>
          )}
          {a.email && (
            <a
              href={`mailto:${a.email}`}
              className="text-accent bg-accent-bg px-2.5 py-1 rounded-md font-medium hover:bg-accent-soft"
            >
              Email
            </a>
          )}
        </div>
        {!a.in_fub && <span className="text-[11px] text-warn">Not in FUB</span>}
        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-accent px-2.5 py-1 hover:bg-accent-bg rounded-md font-medium"
        >
          {expanded ? "▴ Hide profile" : "▾ View profile"}
        </button>
        <div className="flex-1" />
        <div className="inline-flex gap-1">
          {BUCKET_BUTTONS.map((b) => (
            <button
              key={b.key}
              onClick={() => onBucket(b.key)}
              className={
                "text-xs px-2.5 py-1.5 rounded-md border font-medium transition-all " +
                (a.bucket === b.key
                  ? b.on
                  : "bg-card border-border-strong text-text hover:bg-slate-50")
              }
            >
              {b.label}
            </button>
          ))}
        </div>
        <button
          onClick={onSkip}
          title={a.skipped ? "Bring back to natural rank" : "Push to bottom of the list (resets tomorrow)"}
          className={
            "text-xs px-2.5 py-1.5 rounded-md border font-medium " +
            (a.skipped
              ? "bg-slate-100 text-text border-border-strong"
              : "text-muted border-border-strong hover:bg-slate-50")
          }
        >
          {a.skipped ? "Skipped ✓" : "Skip"}
        </button>
        <button
          onClick={onCalled}
          className={
            "text-sm px-3 py-1.5 rounded-md border font-medium " +
            (a.called
              ? "bg-success-bg text-success border-emerald-300"
              : "bg-card border-border-strong text-text hover:bg-slate-50")
          }
        >
          {a.called ? "Called ✓" : "Mark called"}
        </button>
      </div>

      {/* Expanded profile */}
      {expanded && (
        <div className="border-t border-border bg-slate-50/50 p-4 px-[18px] pl-[110px]">
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 mb-3.5 text-sm">
            <Section title="Important dates">
              <Row label="Birthday" value={a.birthday ? fmtDate(a.birthday) : "NA"} />
              <Row label="Anniversary" value={a.anniversary ? fmtAnniversary(a.anniversary) : "NA"} />
            </Section>
            <Section title="Career">
              <Row label="Total tenure" value={a.agent_tenure ? `${(a.agent_tenure / 12).toFixed(1)} yrs` : "—"} />
              <Row
                label="At current office"
                value={a.time_at_current_office ? `${(a.time_at_current_office / 12).toFixed(1)} yrs` : "—"}
              />
              <Row
                label="Office rank"
                value={a.office_rank ? `#${a.office_rank}${a.office_roster_count ? " of " + a.office_roster_count : ""}` : "—"}
              />
            </Section>
            <Section title="Year-over-year trends">
              <TrendRow label="Volume" cur={a.ltm_sales_volume} prev={a.prev_ltm_sales_volume} fmt={fmtMoney} />
              <TrendRow label="Closed units" cur={a.ltm_closed_units} prev={a.prev_ltm_closed_units} fmt={(v) => String(v)} />
              <TrendRow label="Avg sale price" cur={a.ltm_avg_sale_price} prev={a.prev_ltm_avg_sale_price} fmt={fmtMoney} />
            </Section>
            <Section title="Units breakdown (last 12 mo)">
              <Row label="Listing side" value={String(a.ltm_closed_units_list)} />
              <Row label="Buy side" value={String(a.ltm_closed_units_buy)} />
              <Row label="Active / pending" value={`${a.active_listings} / ${a.pending_listings}`} />
              <Row label="Est. GCI" value={fmtMoney(a.ltm_est_gci)} />
            </Section>
            <Section title="Forecast">
              <Row
                label="Predicted next 12 mo"
                value={a.sales_volume_prediction ? fmtMoney(a.sales_volume_prediction) : "—"}
              />
            </Section>
          </div>

          <div className="flex gap-2 mb-3.5 flex-wrap">
            {a.in_fub ? (
              <button
                onClick={onOpenFub}
                className="px-3.5 py-1.5 rounded-lg bg-accent-bg text-accent border border-transparent hover:bg-accent-soft text-sm font-medium"
              >
                Open in FUB ↗
              </button>
            ) : (
              <span className="px-3.5 py-1.5 text-sm text-muted opacity-50">Not in FUB</span>
            )}
            {a.courted_url && (
              <button
                onClick={onOpenCourted}
                className="px-3.5 py-1.5 rounded-lg bg-accent-bg text-accent border border-transparent hover:bg-accent-soft text-sm font-medium"
              >
                Open in Courted ↗
              </button>
            )}
          </div>

          <div>
            <textarea
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="Notes for this call..."
              className="w-full min-h-[64px] resize-y p-2.5 px-3 border border-border-strong rounded-lg text-sm bg-card focus:outline-none focus:border-accent focus:ring-3 focus:ring-accent-bg"
            />
            <div className="flex justify-end mt-1.5 gap-2 items-center">
              <button
                onClick={() => {
                  onSaveNote(noteText);
                  setNoteText("");
                }}
                className="px-3.5 py-1.5 rounded-lg bg-card border border-border-strong text-sm hover:bg-slate-50"
              >
                Save note
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="text-sm">
      <h4 className="m-0 mb-1.5 text-[11px] font-bold text-text uppercase tracking-wider">{title}</h4>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-0.5">
      <span className="text-muted">{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  );
}

function TrendRow({ label, cur, prev, fmt }: { label: string; cur: number; prev: number; fmt: (v: number) => string }) {
  const trend = fmtTrend(cur, prev);
  return (
    <div className="flex justify-between py-0.5">
      <span className="text-muted">{label}</span>
      <span className="tabular-nums">
        {fmt(cur)}{" "}
        {trend.pctText && (
          <span className={trend.klass + " ml-1"}>
            {trend.arrow}
            {trend.pctText}
          </span>
        )}
        {prev > 0 && <span className="text-muted ml-1">(was {fmt(prev)})</span>}
      </span>
    </div>
  );
}

function BucketBadge({ bucket }: { bucket: BucketName }) {
  const styles: Record<BucketName, string> = {
    warm: "bg-amber-50 text-amber-700 border-amber-300",
    nurture: "bg-cyan-50 text-cyan-700 border-cyan-300",
    hot: "bg-rose-50 text-rose-700 border-rose-300",
  };
  return (
    <span
      className={
        "ml-2 text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full border " +
        styles[bucket]
      }
    >
      {bucket}
    </span>
  );
}

function Badge({ color, children }: { color: "success" | "danger" | "warn" | "info" | "pink"; children: React.ReactNode }) {
  const map: Record<string, string> = {
    success: "bg-success-bg text-success",
    danger: "bg-danger-bg text-danger",
    warn: "bg-warn-bg text-warn",
    info: "bg-info-bg text-info",
    pink: "bg-pink-50 text-pink-700",
  };
  return <span className={"text-[11px] px-2 py-0.5 rounded-full leading-relaxed " + map[color]}>{children}</span>;
}
