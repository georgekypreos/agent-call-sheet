import { db } from "./db";
import { CONFIG } from "./config";
import { matchesToday, todayISO } from "./matching";
import { AgentDTO, AgentsResponse, BucketName, BUCKET_NAMES } from "./types";
import type { Agent } from "@prisma/client";

/**
 * The main query that powers every tab. Returns a curated list of agents based on `bucket`:
 *   - ""           → Top ten: 5 highest + 5 lowest LTM closed-units among SREG agents (daily rotation)
 *   - "warm" / "nurture" / "hot" → bucketed agents in that bucket
 *   - "birthday"   → agents whose birthday is today
 *   - "anniversary" → agents whose anniversary is today
 *   - "coops"      → today's 10 Coops rotation slice
 */
export async function loadAgents(opts: { bucket?: string; n?: number }): Promise<AgentsResponse> {
  const bucket = (opts.bucket ?? "").toLowerCase();
  const n = opts.n ?? CONFIG.app.topN;
  const today = todayISO();

  const buckets = await db.bucket.findMany();
  const skipsToday = await db.skipDay.findMany({ where: { date: today } });
  const calledToday = await db.call.findMany({ where: { date: today } });
  const lastSync = await db.syncStatus.findFirst({
    where: { source: "fub-people" },
    orderBy: { lastRunAt: "desc" },
  });

  const bucketByAgentId = new Map<number, BucketName>();
  for (const b of buckets) bucketByAgentId.set(b.agentId, b.name as BucketName);
  const skippedAgentIds = new Set(skipsToday.map((s) => s.agentId));
  const calledAgentIds = new Set(calledToday.map((c) => c.agentId));

  const counts: AgentsResponse["buckets_counts"] = { warm: 0, nurture: 0, hot: 0 };
  for (const b of buckets) {
    const name = b.name as BucketName;
    if (BUCKET_NAMES.includes(name)) counts[name] += 1;
  }

  let pool: Agent[] = [];
  let groupMap = new Map<number, "most" | "least">();

  if (bucket === "coops") {
    const rotation = await db.coopsRotation.findUnique({ where: { date: today } });
    const ids = rotation ? (JSON.parse(rotation.agentIds) as number[]) : [];
    if (ids.length > 0) {
      const rows = await db.agent.findMany({ where: { id: { in: ids } } });
      const byId = new Map(rows.map((r) => [r.id, r]));
      pool = ids.map((id) => byId.get(id)).filter(Boolean) as Agent[];
    }
  } else if (BUCKET_NAMES.includes(bucket as BucketName)) {
    const agentIds = buckets.filter((b) => b.name === bucket).map((b) => b.agentId);
    pool = await db.agent.findMany({ where: { id: { in: agentIds } } });
  } else if (bucket === "birthday") {
    const agents = await db.agent.findMany({ where: { birthday: { not: null } } });
    pool = agents.filter((a) => matchesToday(a.birthday));
  } else if (bucket === "anniversary") {
    const agents = await db.agent.findMany({ where: { anniversary: { not: null } } });
    pool = agents.filter((a) => matchesToday(a.anniversary));
  } else {
    // Top ten: SREG agents, sorted by ltm_closed_units desc, then rotate
    const sreg = await db.agent.findMany({
      where: {
        isSREG: true,
        // Skip blank records: at least tags or office name present
        OR: [{ tagsJson: { not: null } }, { currentOfficeName: { not: "" } }],
      },
    });
    // Exclude bucketed agents from the call list
    const unbucketed = sreg.filter((a) => !bucketByAgentId.has(a.id));
    // Stable sort: closed units desc, then name
    unbucketed.sort((a, b) => {
      const aU = a.ltmClosedUnits ?? 0;
      const bU = b.ltmClosedUnits ?? 0;
      if (aU !== bU) return bU - aU;
      const aN = `${a.firstName ?? ""} ${a.lastName ?? ""}`;
      const bN = `${b.firstName ?? ""} ${b.lastName ?? ""}`;
      return aN.localeCompare(bN);
    });
    const total = unbucketed.length;
    const epoch = new Date("2026-01-01T00:00:00Z").getTime();
    const dayIdx = Math.floor((Date.now() - epoch) / 86400000);
    const half = 5;
    const rotationLen = Math.max(1, Math.ceil(total / (half * 2)));
    const cycleIdx = ((dayIdx % rotationLen) + rotationLen) % rotationLen;
    const topStart = cycleIdx * half;
    const top = unbucketed.slice(topStart, topStart + half);
    const bottomEnd = total - cycleIdx * half;
    const bottomStart = Math.max(topStart + half, bottomEnd - half);
    const bottom = unbucketed.slice(bottomStart, bottomEnd);
    for (const a of top) groupMap.set(a.id, "most");
    for (const a of bottom) groupMap.set(a.id, "least");
    pool = [...top, ...bottom];
  }

  // Split pool into active vs skipped (skipped go to the end)
  const active = pool.filter((a) => !skippedAgentIds.has(a.id));
  const skipped = pool.filter((a) => skippedAgentIds.has(a.id));
  const ordered = [...active, ...skipped];
  const sliced = ordered.slice(0, n);

  // Birthday/anniversary counts for the special tab chips
  const birthdayCount = (await db.agent.findMany({ where: { birthday: { not: null } } })).filter((a) =>
    matchesToday(a.birthday)
  ).length;
  const anniversaryCount = (await db.agent.findMany({ where: { anniversary: { not: null } } })).filter((a) =>
    matchesToday(a.anniversary)
  ).length;
  const coopsRot = await db.coopsRotation.findUnique({ where: { date: today } });
  const coopsCount = coopsRot ? (JSON.parse(coopsRot.agentIds) as number[]).length : 0;

  return {
    last_sync: lastSync?.lastRunAt?.toISOString() ?? null,
    errors: [],
    dry_run: CONFIG.app.dryRun,
    total: ordered.length,
    skipped_today: skipsToday.map((s) => String(s.agentId)),
    buckets_counts: counts,
    special_counts: { coops: coopsCount, birthday: birthdayCount, anniversary: anniversaryCount },
    agents: sliced.map((a, i) =>
      toDTO(a, i + 1, {
        bucket: bucketByAgentId.get(a.id) ?? "",
        skipped: skippedAgentIds.has(a.id),
        called: calledAgentIds.has(a.id),
        group: groupMap.get(a.id) ?? "",
      })
    ),
  };
}

function toDTO(
  a: Agent,
  rank: number,
  extra: { bucket: BucketName | ""; skipped: boolean; called: boolean; group: "most" | "least" | "" }
): AgentDTO {
  const tags: string[] = (() => {
    try {
      return a.tagsJson ? (JSON.parse(a.tagsJson) as string[]) : [];
    } catch {
      return [];
    }
  })();
  const fubUrl = a.fubId ? CONFIG.fub.webUrl.replace("{id}", String(a.fubId)) : "";
  const courtedMlsId =
    a.courtedMlsId ||
    (a.courtedId && a.mlsId ? `${a.courtedId}_${a.mlsId}` : a.courtedId ?? "");
  const courtedUrl = courtedMlsId
    ? CONFIG.courted.webUrl
        .replace("{courted_mls_id}", courtedMlsId)
        .replace("{courted_id}", a.courtedId ?? "")
        .replace("{mls_id}", a.mlsId ?? "")
    : "";

  return {
    rank,
    fubId: a.fubId,
    courtedId: a.courtedId ?? `fub-${a.fubId}`,
    firstName: a.firstName ?? "",
    lastName: a.lastName ?? "",
    email: a.email ?? "",
    phone: a.phone ?? "",
    office: a.currentOfficeName ?? "",
    city: "",
    state: "",
    photo: a.agentPhoto ?? "",
    ltm_sales_volume: a.ltmSalesVolume ?? 0,
    ltm_closed_units: a.ltmClosedUnits ?? 0,
    ltm_closed_units_buy: a.ltmClosedUnitsBuy ?? 0,
    ltm_closed_units_list: a.ltmClosedUnitsList ?? 0,
    ltm_avg_sale_price: a.ltmAvgSalePrice ?? 0,
    ltm_est_gci: a.ltmEstGci ?? 0,
    prev_ltm_sales_volume: a.prevLtmSalesVolume ?? 0,
    prev_ltm_closed_units: a.prevLtmClosedUnits ?? 0,
    prev_ltm_avg_sale_price: a.prevLtmAvgSalePrice ?? 0,
    sales_volume_prediction: a.salesVolumePrediction ?? 0,
    active_listings: a.activeListings ?? 0,
    pending_listings: a.pendingListings ?? 0,
    agent_tenure: a.agentTenure ?? 0,
    time_at_current_office: a.timeAtCurrentOffice ?? 0,
    office_rank: a.officeRank ?? 0,
    office_roster_count: a.officeRosterCount ?? 0,
    ready_to_move: !!a.atReadyToMove,
    trouble_at_office: !!a.atTroubleAtOffice,
    decreasing_sales: !!a.atDecreasingSales,
    fresh_talent: !!a.atFreshTalent,
    predicted_growth: (a.salesVolumePrediction ?? 0) > (a.ltmSalesVolume ?? 0),
    top_15_percent: false,
    called: extra.called,
    in_fub: !!a.fubId,
    birthday: a.birthday ?? "",
    anniversary: a.anniversary ?? "",
    birthday_today: matchesToday(a.birthday),
    anniversary_today: matchesToday(a.anniversary),
    fub_url: fubUrl,
    courted_url: courtedUrl,
    tags,
    score: 0,
    bucket: extra.bucket,
    skipped: extra.skipped,
    group: extra.group,
  };
}
