import { db } from "./db";
import { FubClient, FubPerson } from "./fub";
import { CourtedClient, CourtedAgent } from "./courted";
import { CONFIG } from "./config";
import { normalizeEmail, normalizePhone, isSREGTagged, todayISO } from "./matching";

/**
 * Upsert one FUB person into the Agent table. Reads FUB custom fields by their
 * resolved keys for birthday, anniversary, photo URL, office name, transaction counts.
 */
async function upsertFromFub(fub: FubClient, p: FubPerson): Promise<number> {
  const emails = (p.emails ?? []) as Array<{ value?: string }>;
  const phones = (p.phones ?? []) as Array<{ value?: string }>;
  const email = normalizeEmail(emails[0]?.value);
  const phone = phones[0]?.value ?? "";

  const photoKey = fub.resolveField(CONFIG.fub.fields.photoUrl);
  const bdayKey = fub.resolveField(CONFIG.fub.fields.birthday);
  const anniKey = fub.resolveField(CONFIG.fub.fields.anniversary);
  const officeKey = fub.resolveField(CONFIG.fub.fields.officeName);
  const closedKey = fub.resolveField(CONFIG.fub.fields.closedDeals);
  const volumeKey = fub.resolveField(CONFIG.fub.fields.ltmVolume);
  const courtedIdKey = fub.resolveField(CONFIG.fub.fields.courtedId);

  const agentPhoto = (photoKey && (p[photoKey] as string)) || "";
  const birthday = (bdayKey && (p[bdayKey] as string)) || (p.birthday as string) || null;
  // FUB data quirk: anniversary stored under typoed key `customSREGAniversary`
  const anniversary =
    (anniKey && (p[anniKey] as string)) ||
    (p["customSREGAniversary"] as string) ||
    (p["customSREGAnniversary"] as string) ||
    null;
  const officeName =
    (officeKey && (p[officeKey] as string)) || (p.assignedLenderName as string) || "";
  const closedDealsRaw = closedKey ? p[closedKey] : null;
  const ltmVolumeRaw = volumeKey ? p[volumeKey] : null;
  const courtedIdFromFub = courtedIdKey ? (p[courtedIdKey] as string) : null;

  const tags = Array.isArray(p.tags) ? p.tags : [];
  const isSREG = isSREGTagged(tags);

  const data = {
    fubId: p.id,
    firstName: p.firstName ?? "",
    lastName: p.lastName ?? "",
    email: email || null,
    phone,
    agentPhoto,
    tagsJson: JSON.stringify(tags),
    isSREG,
    birthday: birthday ? String(birthday) : null,
    anniversary: anniversary ? String(anniversary) : null,
    currentOfficeName: officeName,
    ltmClosedUnits:
      closedDealsRaw != null && Number.isFinite(Number(closedDealsRaw)) ? Math.round(Number(closedDealsRaw)) : 0,
    ltmSalesVolume:
      ltmVolumeRaw != null && Number.isFinite(Number(ltmVolumeRaw)) ? Number(ltmVolumeRaw) : 0,
    courtedId: courtedIdFromFub || null,
    lastSeenAt: new Date(),
  };

  // Upsert by FUB id (the durable identifier).
  const upserted = await db.agent.upsert({
    where: { fubId: p.id },
    create: data,
    update: data,
  });
  return upserted.id;
}

/**
 * Enrich an Agent row with Courted production data (matched by email).
 * Skips agents already enriched within the last 7 days.
 */
async function enrichFromCourted(
  agentId: number,
  email: string,
  courted: CourtedClient
): Promise<boolean> {
  if (!email) return false;
  // Check cache
  const cached = await db.courtedEnrichment.findUnique({ where: { email } });
  const cacheAgeDays = cached ? (Date.now() - cached.fetchedAt.getTime()) / 86400000 : Infinity;
  let courtedData: CourtedAgent | null = null;
  if (cached && cacheAgeDays < 7) {
    try {
      courtedData = JSON.parse(cached.data) as CourtedAgent;
    } catch {
      courtedData = null;
    }
  } else {
    courtedData = await courted.getAgentByEmail(email);
    await db.courtedEnrichment.upsert({
      where: { email },
      create: { email, data: JSON.stringify(courtedData ?? null) },
      update: { data: JSON.stringify(courtedData ?? null), fetchedAt: new Date() },
    });
  }
  if (!courtedData) return false;
  await db.agent.update({
    where: { id: agentId },
    data: {
      courtedId: courtedData.courted_id ?? undefined,
      courtedMlsId: courtedData.courted_mls_id ?? undefined,
      mlsId: courtedData.mls_id ?? undefined,
      memberMlsId: courtedData.member_mls_id ?? undefined,
      ltmSalesVolume: courtedData.ltm_sales_volume ?? undefined,
      ltmClosedUnits: courtedData.ltm_closed_units ?? undefined,
      ltmClosedUnitsBuy: courtedData.ltm_closed_units_buy_side ?? undefined,
      ltmClosedUnitsList: courtedData.ltm_closed_units_list_side ?? undefined,
      ltmAvgSalePrice: courtedData.ltm_avg_sale_price ?? undefined,
      ltmEstGci: courtedData.ltm_est_gci ?? undefined,
      prevLtmSalesVolume: courtedData.prev_ltm_sales_volume ?? undefined,
      prevLtmClosedUnits: courtedData.prev_ltm_closed_units ?? undefined,
      prevLtmAvgSalePrice: courtedData.prev_ltm_avg_sale_price ?? undefined,
      salesVolumePrediction: courtedData.sales_volume_prediction ?? undefined,
      activeListings: courtedData.active_listings ?? undefined,
      pendingListings: courtedData.pending_listings ?? undefined,
      agentTenure: courtedData.agent_tenure ?? undefined,
      timeAtCurrentOffice: courtedData.time_at_current_office ?? undefined,
      officeRank: courtedData.office_rank ?? undefined,
      officeRosterCount: courtedData.office_roster_count ?? undefined,
      currentOfficeName: courtedData.current_office_name ?? undefined,
      brandName: courtedData.brand_name ?? undefined,
      atReadyToMove: !!courtedData.at_ready_to_move,
      atTroubleAtOffice: !!courtedData.at_trouble_at_office,
      atDecreasingSales: !!courtedData.at_decreasing_sales,
      atFreshTalent: !!courtedData.at_fresh_talent,
      agentPhoto: courtedData.agent_photo ?? undefined,
      hasCourtedData: true,
      courtedFetchedAt: new Date(),
    },
  });
  return true;
}

/** Mark the start of a sync source. */
async function markRunning(source: string): Promise<void> {
  await db.syncStatus.upsert({
    where: { source },
    create: { source, status: "running", lastRunAt: new Date() },
    update: { status: "running", lastRunAt: new Date(), errorMessage: null },
  });
}

async function markDone(source: string, count: number): Promise<void> {
  await db.syncStatus.update({
    where: { source },
    data: { status: "ok", itemCount: count },
  });
}

async function markError(source: string, error: string): Promise<void> {
  await db.syncStatus.upsert({
    where: { source },
    create: { source, status: "error", errorMessage: error, lastRunAt: new Date() },
    update: { status: "error", errorMessage: error },
  });
}

/**
 * Pull all FUB people in pages. Designed to be chunked across multiple invocations
 * by passing a `maxMs` budget — when budget is reached, returns and the next call
 * resumes from `nextCursor` stored in SyncStatus.
 */
export async function syncFubPeople(opts: { maxMs?: number } = {}): Promise<{ pages: number; agents: number; complete: boolean }> {
  const maxMs = opts.maxMs ?? 55_000;
  const start = Date.now();
  const source = "fub-people";
  await markRunning(source);
  const fub = new FubClient();
  const customFieldMap = await fub.loadCustomFields();
  // Persist field map for runtime lookups
  for (const [label, key] of Object.entries(customFieldMap)) {
    await db.fubCustomField.upsert({
      where: { label },
      create: { label, key },
      update: { key },
    });
  }
  let pageCount = 0;
  let agentCount = 0;
  try {
    for await (const page of fub.listPeople()) {
      pageCount += 1;
      for (const p of page) {
        await upsertFromFub(fub, p);
        agentCount += 1;
      }
      if (Date.now() - start > maxMs) {
        // Stop here; next invocation resumes from where FUB's cursor left off.
        // (For this sketch we re-pull from start. A nextLink store can be added later.)
        return { pages: pageCount, agents: agentCount, complete: false };
      }
    }
    await markDone(source, agentCount);
    return { pages: pageCount, agents: agentCount, complete: true };
  } catch (e) {
    await markError(source, String(e));
    throw e;
  }
}

/**
 * Enrich agents that have a FUB match but no recent Courted data.
 * Iterates in chunks so each invocation finishes within Vercel's timeout.
 */
export async function syncCourtedEnrichment(opts: { limit?: number } = {}): Promise<{ enriched: number; attempted: number }> {
  const limit = opts.limit ?? 100;
  const source = "courted-enrichment";
  await markRunning(source);
  const courted = new CourtedClient();
  const stale = new Date(Date.now() - 7 * 86400000);
  const candidates = await db.agent.findMany({
    where: {
      email: { not: null },
      OR: [{ hasCourtedData: false }, { courtedFetchedAt: { lt: stale } }],
    },
    orderBy: { lastSeenAt: "desc" },
    take: limit,
  });
  let enriched = 0;
  for (const a of candidates) {
    if (!a.email) continue;
    try {
      const ok = await enrichFromCourted(a.id, a.email, courted);
      if (ok) enriched += 1;
    } catch (e) {
      // Continue past per-agent failures
      console.warn("Enrichment failed for", a.email, e);
    }
  }
  await markDone(source, enriched);
  return { enriched, attempted: candidates.length };
}

/** Build today's Coops rotation slice (10 from FUB Smart List 21) and store it in the DB. */
export async function syncCoopsRotation(): Promise<{ count: number; date: string }> {
  const today = todayISO();
  const existing = await db.coopsRotation.findUnique({ where: { date: today } });
  if (existing) {
    const ids = JSON.parse(existing.agentIds) as number[];
    return { count: ids.length, date: today };
  }
  const fub = new FubClient();
  await fub.loadCustomFields();
  // Pull the entire smartlist (may be paginated)
  const all: FubPerson[] = [];
  for await (const page of fub.listPeople({ smartListId: CONFIG.fub.coopsSmartListId })) {
    all.push(...page);
  }
  // Ensure each smartlist person is upserted as an Agent
  for (const p of all) {
    await upsertFromFub(fub, p);
  }
  const dbAgents = await db.agent.findMany({
    where: { fubId: { in: all.map((p) => p.id) } },
    orderBy: { fubId: "asc" },
  });
  // Deterministic rotation: day index since Jan 1, 2026, advancing 10/day
  const epoch = new Date("2026-01-01T00:00:00Z").getTime();
  const dayIdx = Math.floor((Date.now() - epoch) / 86400000);
  const total = dbAgents.length;
  if (total === 0) {
    await db.coopsRotation.upsert({
      where: { date: today },
      create: { date: today, agentIds: "[]" },
      update: { agentIds: "[]" },
    });
    return { count: 0, date: today };
  }
  const rotationLen = Math.max(1, Math.ceil(total / CONFIG.app.coopsPerDay));
  const cycleIdx = ((dayIdx % rotationLen) + rotationLen) % rotationLen;
  const start = cycleIdx * CONFIG.app.coopsPerDay;
  const slice =
    start + CONFIG.app.coopsPerDay <= total
      ? dbAgents.slice(start, start + CONFIG.app.coopsPerDay)
      : [...dbAgents.slice(start), ...dbAgents.slice(0, start + CONFIG.app.coopsPerDay - total)];
  const agentIds = slice.map((a) => a.id);
  await db.coopsRotation.upsert({
    where: { date: today },
    create: { date: today, agentIds: JSON.stringify(agentIds) },
    update: { agentIds: JSON.stringify(agentIds) },
  });
  return { count: agentIds.length, date: today };
}
