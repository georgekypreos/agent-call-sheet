import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { CONFIG } from "@/lib/config";
import { FubClient, fubError } from "@/lib/fub";

export const runtime = "nodejs";

/**
 * POST /api/note/[fubId]
 * Body: { note: string }
 * Saves a note to FUB's /notes endpoint (unless dry-run) and to our local DB for reference.
 */
export async function POST(req: NextRequest, { params }: { params: { fubId: string } }) {
  const fubId = Number(params.fubId);
  if (!Number.isFinite(fubId)) return NextResponse.json({ ok: false, error: "Invalid fubId" }, { status: 400 });
  const body = await req.json().catch(() => ({}));
  const note: string = (body.note ?? "").toString().trim();
  if (!note) return NextResponse.json({ ok: false, error: "Empty note" }, { status: 400 });
  const agent = await db.agent.findUnique({ where: { fubId } });
  if (!agent) return NextResponse.json({ ok: false, error: "Agent not found" }, { status: 404 });

  let fubNoteId: string | null = null;
  let syncStatus: "synced" | "dry_run" | "error" = "dry_run";
  let syncError: string | null = null;
  if (!CONFIG.app.dryRun) {
    try {
      const res = await new FubClient().addNote(fubId, note);
      fubNoteId = res.id ? String(res.id) : null;
      syncStatus = "synced";
    } catch (e) {
      syncStatus = "error";
      syncError = fubError(e);
    }
  }
  await db.note.create({
    data: { agentId: agent.id, body: note, fubNoteId, syncStatus, syncError },
  });
  return NextResponse.json({ ok: syncStatus !== "error", dry_run: CONFIG.app.dryRun, error: syncError ?? undefined });
}
