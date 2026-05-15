import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { BUCKET_NAMES, BucketName } from "@/lib/types";

export const runtime = "nodejs";

/**
 * POST /api/bucket/[fubId]
 * Body: { bucket: "warm" | "nurture" | "hot" | "" | null }
 * Moves an agent into the given bucket, removing them from any other bucket. Pass empty/null to un-bucket.
 */
export async function POST(req: NextRequest, { params }: { params: { fubId: string } }) {
  const fubId = Number(params.fubId);
  if (!Number.isFinite(fubId)) return NextResponse.json({ ok: false, error: "Invalid fubId" }, { status: 400 });
  const body = await req.json().catch(() => ({}));
  const target = (body.bucket ?? "").trim().toLowerCase();
  const agent = await db.agent.findUnique({ where: { fubId } });
  if (!agent) return NextResponse.json({ ok: false, error: "Agent not found" }, { status: 404 });

  if (target && !BUCKET_NAMES.includes(target as BucketName)) {
    return NextResponse.json({ ok: false, error: `Unknown bucket '${target}'` }, { status: 400 });
  }

  // One bucket per agent — replace any existing.
  await db.bucket.deleteMany({ where: { agentId: agent.id } });
  if (target) {
    await db.bucket.create({ data: { agentId: agent.id, name: target } });
  }
  const counts: Record<BucketName, number> = { warm: 0, nurture: 0, hot: 0 };
  for (const name of BUCKET_NAMES) {
    counts[name] = await db.bucket.count({ where: { name } });
  }
  return NextResponse.json({ ok: true, bucket: target || null, counts });
}
