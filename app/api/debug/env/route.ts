import { NextResponse } from "next/server";

export const runtime = "nodejs";

/**
 * Debug-only endpoint: confirms which env vars are loaded WITHOUT exposing them.
 * GET /api/debug/env
 */
export async function GET() {
  const mask = (v: string | undefined): string => {
    if (!v) return "(missing)";
    if (v.length < 6) return "(set, " + v.length + " chars)";
    return v.slice(0, 4) + "..." + v.slice(-2) + " (" + v.length + " chars)";
  };
  return NextResponse.json({
    DATABASE_URL: mask(process.env.DATABASE_URL),
    FUB_API_KEY: mask(process.env.FUB_API_KEY),
    FUB_BASE_URL: process.env.FUB_BASE_URL ?? "(missing — using default)",
    COURTED_API_KEY: mask(process.env.COURTED_API_KEY),
    COURTED_BASE_URL: process.env.COURTED_BASE_URL ?? "(missing — using default)",
    NODE_ENV: process.env.NODE_ENV,
  });
}
