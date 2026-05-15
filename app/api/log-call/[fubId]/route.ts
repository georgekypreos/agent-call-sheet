import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { todayISO } from "@/lib/matching";
import { CONFIG } from "@/lib/config";
import { FubClient, fubError } from "@/lib/fub";

export const runtime = "nodejs";

/**
 * POST /api/log-call/[fubId]
 * Body: { outcome?: string, duration_seconds?: number, note?: string }
 *
 * Logs a Call activity to FUB so it shows on the contact's timeline.
 * Also writes a row to our `Call` table for daily progress tracking.
 */
export async function POST(req: NextRequest, { params }: { params: { fubId: string } }) {
  const fubId = Number(params.fubId);
  if (!Number.isFinite(fubId)) return NextResponse.json({ ok: false, error: "Invalid fubId" }, { status: 400 });
  const body = await req.json().catch(() => ({}));
  const outcome: string = (body.outcome ?? "Reached").toString();
  const durationSec: number = Number(body.duration_seconds ?? 300);
  const note: string = (body.note ?? "").toString();
  const today = todayISO();
  const agent = await db.agent.findUnique({ where: { fubId } });
  if (!agent) return NextResponse.json({ ok: false, error: "Agent not found" }, { status: 404 });

  // Always record locally so the progress bar updates immediately.
  let fubCallId: string | null = null;
  let syncStatus: "synced" | "dry_run" | "error" = "dry_run";
  let syncError: string | null = null;
  if (!CONFIG.app.dryRun) {
    try {
      const res = await new FubClient().logCall({
        personId: fubId,
        outcome,
        durationSeconds: durationSec,
        note,
      });
      fubCallId = res.id ? String(res.id) : null;
      syncStatus = "synced";
    } catch (e) {
      syncStatus = "error";
      syncError = fubError(e);
    }
  }
  await db.call.create({
    data: {
      agentId: agent.id,
      outcome,
      durationSec,
      note,
      fubCallId,
      syncStatus,
      syncError,
      date: today,
    },
  });
  return NextResponse.json({ ok: syncStatus !== "error", dry_run: CONFIG.app.dryRun, error: syncError ?? undefined });
}
