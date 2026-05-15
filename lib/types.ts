/**
 * Shared types used across server and client. Keep these portable — no Node-only imports.
 */

export type BucketName = "warm" | "nurture" | "hot";
export const BUCKET_NAMES = ["warm", "nurture", "hot"] as const;

export type SpecialTab = "coops" | "birthday" | "anniversary";
export const SPECIAL_TABS = ["coops", "birthday", "anniversary"] as const;

export type TabKey = "" | BucketName | SpecialTab;

export type CallOutcome = "Reached" | "Left Message" | "No Answer" | "Bad Number" | "Busy";

/**
 * Shape returned by /api/agents — what the dashboard renders.
 * `group` is set on Top ten tab cards ("most" or "least") so the UI can insert the divider.
 */
export interface AgentDTO {
  rank: number;
  fubId: number;
  courtedId: string;
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
  office: string;
  city: string;
  state: string;
  photo: string;
  // Production
  ltm_sales_volume: number;
  ltm_closed_units: number;
  ltm_closed_units_buy: number;
  ltm_closed_units_list: number;
  ltm_avg_sale_price: number;
  ltm_est_gci: number;
  prev_ltm_sales_volume: number;
  prev_ltm_closed_units: number;
  prev_ltm_avg_sale_price: number;
  sales_volume_prediction: number;
  active_listings: number;
  pending_listings: number;
  agent_tenure: number;
  time_at_current_office: number;
  office_rank: number;
  office_roster_count: number;
  // Signals
  ready_to_move: boolean;
  trouble_at_office: boolean;
  decreasing_sales: boolean;
  fresh_talent: boolean;
  predicted_growth: boolean;
  top_15_percent: boolean;
  // State
  called: boolean;
  in_fub: boolean;
  birthday: string;
  anniversary: string;
  birthday_today: boolean;
  anniversary_today: boolean;
  fub_url: string;
  courted_url: string;
  tags: string[];
  score: number;
  bucket: BucketName | "";
  skipped: boolean;
  group: "most" | "least" | "";
}

export interface AgentsResponse {
  last_sync: string | null;
  errors: string[];
  dry_run: boolean;
  total: number;
  skipped_today: string[];
  buckets_counts: Record<BucketName, number>;
  special_counts: Record<SpecialTab, number>;
  agents: AgentDTO[];
}
