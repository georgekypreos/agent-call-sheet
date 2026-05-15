import axios, { AxiosInstance, AxiosError } from "axios";
import { CONFIG } from "./config";

/**
 * Follow Up Boss API client. Auth via HTTP Basic with the API key as the username.
 * Docs: https://docs.followupboss.com/reference
 */
export class FubClient {
  private http: AxiosInstance;
  private customFieldMap: Record<string, string> = {};

  constructor() {
    const key = CONFIG.fub.apiKey;
    if (!key) throw new Error("FUB_API_KEY is not configured");
    this.http = axios.create({
      baseURL: CONFIG.fub.baseUrl,
      auth: { username: key, password: "" },
      headers: {
        "X-System": CONFIG.fub.systemName,
        "X-System-Key": CONFIG.fub.systemKey,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      timeout: 30000,
    });
  }

  /**
   * Pulls every custom field definition from FUB so we can resolve labels like
   * "Birthday" → "customBirthday" at runtime.
   */
  async loadCustomFields(): Promise<Record<string, string>> {
    const out: Record<string, string> = {};
    for (const path of ["/customFields", "/customfields"]) {
      try {
        const { data } = await this.http.get(path, { params: { limit: 100 } });
        const fields = data.customFields ?? data.customfields ?? data.data ?? [];
        for (const f of fields) {
          const label = f.label ?? f.name;
          const name = f.name;
          if (label && name) out[String(label)] = String(name);
        }
        if (Object.keys(out).length > 0) break;
      } catch {
        // try next path
      }
    }
    this.customFieldMap = out;
    return out;
  }

  /** Resolve a label like "Birthday" to its internal key like "customBirthday". */
  resolveField(label: string | undefined | null): string | null {
    if (!label) return null;
    if (this.customFieldMap[label]) return this.customFieldMap[label];
    const target = label.trim().toLowerCase();
    for (const [lbl, key] of Object.entries(this.customFieldMap)) {
      if (lbl.trim().toLowerCase() === target) return key;
    }
    for (const key of Object.values(this.customFieldMap)) {
      if (key.toLowerCase() === target) return key;
    }
    return label; // last resort: treat as direct key
  }

  /**
   * Cursor-paginated list of all people at the configured stage. Yields pages
   * so the caller can stream into the DB and stay under Vercel's 60s timeout.
   */
  async *listPeople(opts: { limit?: number; smartListId?: number } = {}): AsyncGenerator<FubPerson[]> {
    const limit = opts.limit ?? 100;
    let url: string | null = "/people";
    let params: Record<string, string | number> | undefined = {
      limit,
      includeTrash: "false",
      sort: "created",
      fields: "allFields",
    };
    if (CONFIG.fub.stageFilter && !opts.smartListId) params!.stage = CONFIG.fub.stageFilter;
    if (opts.smartListId) params!.smartListId = opts.smartListId;
    while (url) {
      const { data } = await this.http.get(url, { params: url === "/people" ? params : undefined });
      const people: FubPerson[] = data.people ?? [];
      yield people;
      const meta = data._metadata ?? {};
      const next = meta.nextLink ?? meta.next ?? null;
      if (!next || people.length === 0) break;
      url = next as string;
      params = undefined;
    }
  }

  async addNote(personId: number, body: string): Promise<{ id?: number } & Record<string, unknown>> {
    const { data } = await this.http.post("/notes", { personId, body });
    return data;
  }

  async logCall(opts: {
    personId: number;
    outcome?: string;
    durationSeconds?: number;
    note?: string;
    direction?: "Outbound" | "Inbound";
  }): Promise<{ id?: number } & Record<string, unknown>> {
    const { data } = await this.http.post("/calls", {
      personId: opts.personId,
      outcome: opts.outcome ?? "Reached",
      duration: opts.durationSeconds ?? 300,
      note: opts.note ?? "",
      direction: opts.direction ?? "Outbound",
    });
    return data;
  }

  async updatePerson(personId: number, payload: Record<string, unknown>): Promise<void> {
    await this.http.put(`/people/${personId}`, payload);
  }

  async createPerson(payload: Record<string, unknown>): Promise<FubPerson> {
    const { data } = await this.http.post("/people", payload);
    return data;
  }

  /** Add or remove a tag on a person. Read-modify-write since FUB's PUT replaces the array. */
  async setTag(personId: number, tag: string, present: boolean): Promise<void> {
    const { data: person } = await this.http.get(`/people/${personId}`, {
      params: { fields: "tags" },
    });
    const current = Array.isArray(person.tags) ? (person.tags as string[]) : [];
    let next = current;
    if (present && !current.includes(tag)) next = [...current, tag];
    else if (!present && current.includes(tag)) next = current.filter((t) => t !== tag);
    if (next !== current) {
      await this.http.put(`/people/${personId}`, { tags: next });
    }
  }
}

/** Minimal shape of a FUB person record — there are many more fields available via fields=allFields. */
export interface FubPerson {
  id: number;
  firstName?: string;
  lastName?: string;
  emails?: Array<{ value?: string; isPrimary?: number; type?: string }>;
  phones?: Array<{ value?: string; isPrimary?: number; type?: string }>;
  stage?: string;
  tags?: string[];
  assignedLenderName?: string;
  birthday?: string | null;
  // Custom fields appear inline as customXxx keys
  [key: string]: unknown;
}

export function fubError(e: unknown): string {
  if (e instanceof AxiosError) {
    const status = e.response?.status;
    const detail = e.response?.data?.errorMessage ?? e.response?.data?.message ?? e.message;
    return `FUB ${status ?? ""} ${detail}`.trim();
  }
  return String(e);
}
