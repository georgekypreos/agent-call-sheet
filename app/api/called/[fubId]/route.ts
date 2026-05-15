import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { todayISO } from "@/lib/matching";
import { CONFIG } from "@/lib/config";
import { FubClient, fubError } from "@/lib/fub";

export const runtime = "nodejs";

/**
 * POST /api/called/[fubId]
 * Body: { called: boolean }
 *
 * Toggles the "called today" state for an agent. When marking as called:
 *   - Creates a row in `Call` table (we use this to count daily progress).
 *   - Tags the FUB contact with `called-YYYY-MM-DD` (unless dry-run).
 * When un-marking, the call row is deleted and the tag is removed.
 */
export async function POST(req: NextRequest, { params }: { params: { fubId: string } }) {
  const fubId = Number(params.fubId);
  if (!Number.isFinite(fubId)) return NextResponse.json({ ok: false, error: "Invalid fubId" }, { status: 400 });
  const body = await req.json().catch(() => ({}));
  const called: boolean = body.called !== false;
  const today = todayISO();
  const agent = await db.agent.findUnique({ where: { fubId } });
  if (!agent) return NextResponse.json({ ok: false, error: "Agent not found" }, { status: 404 });

  if (called) {
    // Avoid duplicate today rows
    const existing = await db.call.findFirst({ where: { agentId: agent.id, date: today } });
    if (!existing) {
      await db.call.create({
        data: { agentId: agent.id, date: today, syncStatus: CONFIG.app.dryRun ? "dry_run" : "pending" },
      });
    }
  } else {
    await db.call.deleteMany({ where: { agentId: agent.id, date: today } });
  }

  // Tag in FUB (read-modify-write). Skipped in dry-run.
  if (!CONFIG.app.dryRun) {
    try {
      const tag = CONFIG.fub.calledTagTemplate.replace("{date}", today);
      const fub = new FubClient();
      await fub.setTag(fubId, tag, called);
    } catch (e) {
      return NextResponse.json({ ok: false, error: fubError(e) }, { status: 500 });
    }
  }
  return NextResponse.json({ ok: true, dry_run: CONFIG.app.dryRun });
}
