import { NextRequest, NextResponse } from "next/server";
import { loadAgents } from "@/lib/agents";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const bucket = url.searchParams.get("bucket") ?? "";
  const n = parseInt(url.searchParams.get("n") ?? "10", 10);
  try {
    const data = await loadAgents({ bucket, n });
    return NextResponse.json(data);
  } catch (e) {
    console.error("[/api/agents] failed:", e);
    const msg = e instanceof Error ? `${e.name}: ${e.message}\n${e.stack ?? ""}` : String(e);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
