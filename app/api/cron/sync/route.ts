import { NextRequest, NextResponse } from "next/server";
import { syncFubPeople, syncCourtedEnrichment, syncCoopsRotation } from "@/lib/sync";
import { CONFIG } from "@/lib/config";

export const runtime = "nodejs";
export const maxDuration = 60;

/**
 * Vercel Cron entry point — wired up in vercel.json with a daily schedule.
 * Vercel includes the header `Authorization: Bearer <CRON_SECRET>` when calling this.
 */
export async function GET(req: NextRequest) {
  const auth = req.headers.get("authorization") ?? "";
  if (CONFIG.cronSecret && auth !== `Bearer ${CONFIG.cronSecret}`) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }
  try {
    const fub = await syncFubPeople({ maxMs: 50_000 });
    const enrich = await syncCourtedEnrichment({ limit: 100 });
    const coops = await syncCoopsRotation();
    return NextResponse.json({ ok: true, fub, enrich, coops });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
