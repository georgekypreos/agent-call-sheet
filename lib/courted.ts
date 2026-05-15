import axios, { AxiosInstance, AxiosError } from "axios";
import { CONFIG } from "./config";

/**
 * Courted API client. Auth uses a Token-style scheme (`Authorization: Token <key>`),
 * NOT Bearer — that's important. Pagination is DRF-style (count/next/previous/results),
 * and the `next` URL often returns the wrong internal host so we rewrite it.
 */
export class CourtedClient {
  private http: AxiosInstance;

  constructor() {
    const key = CONFIG.courted.apiKey;
    if (!key) throw new Error("COURTED_API_KEY is not configured");
    this.http = axios.create({
      baseURL: CONFIG.courted.baseUrl,
      headers: {
        Authorization: `${CONFIG.courted.authScheme} ${key}`,
        Accept: "application/json",
      },
      timeout: 30000,
    });
  }

  async healthCheck(): Promise<boolean> {
    try {
      await this.http.get("/health");
      return true;
    } catch {
      return false;
    }
  }

  /** Fix the broken next URL Courted sometimes returns (apiserver:80 instead of api.courted.io). */
  private fixNextUrl(url: string | null | undefined): string | null {
    if (!url) return null;
    return url
      .replace(/https?:\/\/apiserver(:80)?\//, `${CONFIG.courted.baseUrl.replace(/\/api\/v1$/, "")}/`)
      .replace(/^http:\/\//, "https://");
  }

  /** Generic paginated GET; yields each page's results array. */
  async *paginate<T = Record<string, unknown>>(path: string, params: Record<string, string | number> = {}): AsyncGenerator<T[]> {
    let url: string | null = path;
    let isFirst = true;
    while (url) {
      try {
        const { data } = await this.http.get(url, {
          params: isFirst ? { limit: 100, ...params } : undefined,
          // For pages 2+ we use the full URL so axios baseURL doesn't double up
          baseURL: isFirst ? this.http.defaults.baseURL : "",
        });
        isFirst = false;
        const results: T[] = data.results ?? data.data ?? [];
        yield results;
        url = this.fixNextUrl(data.next ?? null);
        if (results.length === 0) break;
      } catch (e) {
        if (e instanceof AxiosError && e.response?.status === 429) {
          // Hit the 1000-records-per-session cap; return what we have so far.
          return;
        }
        throw e;
      }
    }
  }

  async getAgentByEmail(email: string): Promise<CourtedAgent | null> {
    try {
      const { data } = await this.http.get("/agent", { params: { email } });
      // The endpoint may return either a list or a single object depending on the API version.
      if (Array.isArray(data?.results) && data.results[0]) return data.results[0];
      if (data?.id || data?.courted_id) return data;
      return null;
    } catch (e) {
      if (e instanceof AxiosError && (e.response?.status === 404 || e.response?.status === 429)) return null;
      throw e;
    }
  }

  /** Pull the company pipeline (every agent in the user's market reach). */
  async *listPipelineAgents(): AsyncGenerator<CourtedAgent[]> {
    yield* this.paginate<CourtedAgent>("/company/pipeline/agents");
  }
}

export interface CourtedAgent {
  courted_id?: string;
  courted_mls_id?: string;
  member_mls_id?: string;
  mls_id?: string;
  first_name?: string;
  last_name?: string;
  email?: string;
  phone?: string;
  mobile_phone?: string;
  agent_photo?: string | null;
  current_office_name?: string;
  current_office_city?: string;
  current_office_state?: string;
  brand_name?: string;
  ltm_sales_volume?: number;
  ltm_closed_units?: number;
  ltm_closed_units_buy_side?: number;
  ltm_closed_units_list_side?: number;
  ltm_avg_sale_price?: number;
  ltm_est_gci?: number;
  prev_ltm_sales_volume?: number;
  prev_ltm_closed_units?: number;
  prev_ltm_avg_sale_price?: number;
  sales_volume_prediction?: number;
  active_listings?: number;
  pending_listings?: number;
  agent_tenure?: number;
  time_at_current_office?: number;
  office_rank?: number;
  office_roster_count?: number;
  at_ready_to_move?: boolean;
  at_trouble_at_office?: boolean;
  at_decreasing_sales?: boolean;
  at_fresh_talent?: boolean;
  most_transacted_city?: string;
  [key: string]: unknown;
}

export function courtedError(e: unknown): string {
  if (e instanceof AxiosError) {
    const status = e.response?.status;
    const detail = e.response?.data?.detail ?? e.response?.data?.message ?? e.message;
    return `Courted ${status ?? ""} ${detail}`.trim();
  }
  return String(e);
}
