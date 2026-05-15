/**
 * Centralized runtime config. All values come from environment variables (loaded by Next.js).
 * Local dev: .env.local at the project root.
 * Production: Vercel Project Settings → Environment Variables.
 */

function env(key: string, fallback?: string): string {
  const v = process.env[key];
  if (v === undefined || v === "") {
    if (fallback !== undefined) return fallback;
    throw new Error(`Missing required environment variable: ${key}`);
  }
  return v;
}

function envOptional(key: string, fallback = ""): string {
  return process.env[key] ?? fallback;
}

function envBool(key: string, fallback = false): boolean {
  const v = process.env[key];
  if (v === undefined) return fallback;
  return v.toLowerCase() === "true" || v === "1";
}

function envInt(key: string, fallback: number): number {
  const v = process.env[key];
  if (!v) return fallback;
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : fallback;
}

function envJson<T>(key: string, fallback: T): T {
  const v = process.env[key];
  if (!v) return fallback;
  try {
    return JSON.parse(v) as T;
  } catch {
    return fallback;
  }
}

export const CONFIG = {
  fub: {
    apiKey: envOptional("FUB_API_KEY"),
    baseUrl: envOptional("FUB_BASE_URL", "https://api.followupboss.com/v1"),
    systemName: envOptional("FUB_SYSTEM_NAME", "AgentCallSheet"),
    systemKey: envOptional("FUB_SYSTEM_KEY", "agent-call-sheet-local"),
    stageFilter: envOptional("FUB_STAGE_FILTER", "Agents"),
    calledTagTemplate: envOptional("FUB_CALLED_TAG_TEMPLATE", "called-{date}"),
    webUrl: envOptional("FUB_WEB_URL", "https://app.followupboss.com/2/people/view/{id}"),
    coopsSmartListId: envInt("COOPS_SMARTLIST_ID", 21),
    fields: {
      photoUrl: envOptional("FUB_FIELD_PHOTO_URL", "Photo URL"),
      courtedId: envOptional("FUB_FIELD_COURTED_ID", "Courted ID"),
      lastCalled: envOptional("FUB_FIELD_LAST_CALLED", "Last Called"),
      priorityScore: envOptional("FUB_FIELD_PRIORITY_SCORE", "Priority Score"),
      birthday: envOptional("FUB_FIELD_BIRTHDAY", "Birthday"),
      anniversary: envOptional("FUB_FIELD_ANNIVERSARY", "customSREGAniversary"),
      officeName: envOptional("FUB_FIELD_OFFICE_NAME", "Office Name"),
      closedDeals: envOptional("FUB_FIELD_CLOSED_DEALS", "Closed Deals"),
      ltmVolume: envOptional("FUB_FIELD_LTM_VOLUME", "LTM Sales Volume"),
    },
  },
  courted: {
    apiKey: envOptional("COURTED_API_KEY"),
    authScheme: envOptional("COURTED_AUTH_SCHEME", "Token"),
    baseUrl: envOptional("COURTED_BASE_URL", "https://api.courted.io/api/v1"),
    source: envOptional("COURTED_SOURCE", "pipeline"),
    webUrl: envOptional("COURTED_WEB_URL", "https://brokerage.courted.io/candidates/agent_{courted_mls_id}"),
  },
  app: {
    topN: envInt("TOP_N", 10),
    dryRun: envBool("DRY_RUN", true),
    autoCreateInFub: envBool("AUTO_CREATE_IN_FUB", false),
    coopsPerDay: 10,
  },
  scoringWeights: envJson<{
    volume_per_million_capped_at: number;
    ready_to_move: number;
    trouble_at_office: number;
    decreasing_sales: number;
    fresh_talent: number;
    predicted_growth: number;
    per_closed_unit: number;
    called_penalty: number;
  }>("SCORING_WEIGHTS", {
    volume_per_million_capped_at: 100,
    ready_to_move: 50,
    trouble_at_office: 30,
    decreasing_sales: 25,
    fresh_talent: 20,
    predicted_growth: 15,
    per_closed_unit: 0.5,
    called_penalty: 1000,
  }),
  cronSecret: envOptional("CRON_SECRET"),
};

export type Config = typeof CONFIG;
