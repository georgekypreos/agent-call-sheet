import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { todayISO } from "@/lib/matching";

export const runtime = "nodejs";

/**
 * POST /api/skip/[fubId]
 * Body: { skip: boolean }
 * Per-day skip. Auto-resets at midnight because the SkipDay key is (agentId, today's date).
 */
export async function POST(req: NextRequest, { params }: { params: { fubId: string } }) {
  const fubId = Number(params.fubId);
  if (!Number.isFinite(fubId)) return NextResponse.json({ ok: false, error: "Invalid fubId" }, { status: 400 });
  const body = await req.json().catch(() => ({}));
  const skip: boolean = body.skip !== false;
  const today = todayISO();
  const agent = await db.agent.findUnique({ where: { fubId } });
  if (!agent) return NextResponse.json({ ok: false, error: "Agent not found" }, { status: 404 });

  if (skip) {
    await db.skipDay.upsert({
      where: { agentId_date: { agentId: agent.id, date: today } },
      create: { agentId: agent.id, date: today },
      update: {},
    });
  } else {
    await db.skipDay.deleteMany({ where: { agentId: agent.id, date: today } });
  }
  const count = await db.skipDay.count({ where: { date: today } });
  return NextResponse.json({ ok: true, skipped: skip, count_today: count });
}
