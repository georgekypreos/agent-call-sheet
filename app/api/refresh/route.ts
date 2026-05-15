import { NextRequest, NextResponse } from "next/server";
import { syncFubPeople, syncCourtedEnrichment, syncCoopsRotation } from "@/lib/sync";

export const runtime = "nodejs";
export const maxDuration = 60; // seconds (Vercel Pro). Hobby is 10s — split into chunks if hitting that.

/**
 * POST /api/refresh
 * Manually trigger a sync. Designed to fit within Vercel's 60s timeout — runs the FUB pull
 * in chunks, then a batch of Courted enrichment, then refreshes the Coops rotation.
 */
export async function POST(_req: NextRequest) {
  try {
    const fub = await syncFubPeople({ maxMs: 45_000 });
    const enrich = await syncCourtedEnrichment({ limit: 50 });
    const coops = await syncCoopsRotation();
    return NextResponse.json({
      ok: true,
      fub_complete: fub.complete,
      fub_pages: fub.pages,
      fub_agents: fub.agents,
      enriched: enrich.enriched,
      coops_count: coops.count,
    });
  } catch (e) {
    console.error("[/api/refresh] sync failed:", e);
    const msg = e instanceof Error ? `${e.name}: ${e.message}\n${e.stack ?? ""}` : String(e);
    return NextResponse.json({ ok: false, error: msg }, { status: 500 });
  }
}
