import type {
  LiveMatchWithOdds,
  PaginatedResponse,
  PaginatedMatchesResponse,
  UpcomingMatchWithOdds,
} from "@/app/types/pandascore";
import type {
  ActiveBet,
  ActiveSeriesPositionGroup,
  BankrollSummary,
  MatchBettingStatus,
  OpenBetScheduleStatus,
} from "@/app/types/Betting";
import type { PowerRankingRow } from "@/app/types/PowerRanking";
import type { Result, ResultsAnalytics } from "@/app/types/Result";

export interface OddsRefreshStatus {
  allowed: boolean;
  next_available_at: string | null;
}

export interface OddsRefreshAccepted {
  status: "accepted";
  message: string;
  task_ids: string[];
}

export interface OddsRefreshLocked {
  status: "locked";
  message: string;
  next_available_at: string | null;
}

export interface OddsRefreshProgress {
  status: "pending" | "running" | "success" | "error";
  progress: number;
  stage: string;
  done: boolean;
  message: string | null;
}

export interface OddsRefreshGlobalStatus {
  in_progress: boolean;
  task_id?: string | null;
  progress?: number;
  stage?: string;
  last_completed_at?: string | null;
  next_scheduled_at?: string | null;
}

export interface HomepageBootstrapResponse {
  generated_at: string | null;
  results_generated_at: string | null;
  upcoming: PaginatedMatchesResponse<UpcomingMatchWithOdds>;
  live: PaginatedMatchesResponse<LiveMatchWithOdds>;
  bankroll: BankrollSummary | null;
  active_bets: ActiveBet[];
  active_positions_by_series: ActiveSeriesPositionGroup[];
  match_betting_statuses: MatchBettingStatus[];
  power_rankings_preview: PowerRankingRow[];
  refresh_status: OddsRefreshGlobalStatus;
  section_status?: Record<string, Record<string, unknown>>;
}

interface OddsQueryOptions {
  page?: number;
  perPage?: number;
  tier?: string | null;
  search?: string;
  leagues?: string[];
}

interface HistoryQueryOptions {
  page?: number;
  perPage?: number;
  search?: string;
  leagues?: string[];
}

const MISSING_API_URL_MESSAGE =
  "API URL is not set. Configure VITE_API_URL (or NEXT_PUBLIC_API_URL for compatibility) to your backend URL (e.g. http://localhost:8000).";

function isLocalHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1";
}

function readEnv(name: string): string {
  const viteValue = import.meta.env[name as keyof ImportMetaEnv];
  if (typeof viteValue === "string" && viteValue.length > 0) {
    return viteValue;
  }
  const processValue = (globalThis as { process?: { env?: Record<string, string | undefined> } })
    .process?.env?.[name];
  return processValue ?? "";
}

export function getApiBaseUrl(): string {
  const env = readEnv("VITE_API_URL") || readEnv("NEXT_PUBLIC_API_URL");
  if (env) {
    return env.replace(/\/$/, "");
  }
  if (typeof window !== "undefined") {
    const hostname = window.location?.hostname ?? "";
    if (isLocalHostname(hostname)) {
      return "http://localhost:8000";
    }
    return "";
  }
  return "";
}

function apiUrl(path: string): string {
  const base = getApiBaseUrl();
  const segment = path.startsWith("/") ? path : `/${path}`;
  if (!base) {
    return `/api/v1${segment}`;
  }
  if (base.endsWith("/api/v1")) {
    return `${base}${segment}`;
  }
  return `${base}/api/v1${segment}`;
}

function apiHeaders(extra: HeadersInit = {}): HeadersInit {
  return {
    Accept: "application/json",
    ...(extra as Record<string, string>),
  };
}

async function fetchJson<T>(input: string, init: RequestInit, context: string): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: apiHeaders(init.headers),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(apiErrorMessage(context, response.status, text));
  }
  return (await response.json()) as T;
}

function requireApiBase(): void {
  const base = getApiBaseUrl();
  if (!base && typeof window === "undefined") {
    throw new Error(MISSING_API_URL_MESSAGE);
  }
}

function apiErrorMessage(context: string, status: number, bodyText: string): string {
  if (status === 404) {
    return "Backend not reachable (404). Is the API running and API URL correct?";
  }
  if (status === 502 || status === 503) {
    return "Server temporarily unavailable. Try again in a moment.";
  }
  const trimmed = bodyText.trim();
  const isHtml =
    trimmed.startsWith("<!") ||
    trimmed.startsWith("<html") ||
    trimmed.toLowerCase().includes("<!doctype");
  const detail = isHtml ? "" : ` — ${trimmed.slice(0, 150)}`;
  return `${context} failed: ${status}${detail}`;
}

function appendFilterParams(
  params: URLSearchParams,
  options: {
    search?: string;
    leagues?: string[];
  },
): void {
  const search = options.search?.trim();
  if (search) params.set("search", search);
  if (options.leagues && options.leagues.length > 0) {
    params.set("league", options.leagues.join(","));
  }
}

export async function fetchUpcomingWithOdds(
  {
    perPage = 10,
    page = 1,
    tier = "s,a",
    search = "",
    leagues = [],
  }: OddsQueryOptions = {},
): Promise<PaginatedMatchesResponse<UpcomingMatchWithOdds>> {
  requireApiBase();
  const params = new URLSearchParams({
    per_page: String(perPage),
    page: String(page),
  });
  if (tier) params.set("tier", tier);
  appendFilterParams(params, { search, leagues });
  const url = `${apiUrl("/pandascore/lol/upcoming-with-odds")}?${params.toString()}`;
  return fetchJson<PaginatedMatchesResponse<UpcomingMatchWithOdds>>(url, {}, "Upcoming with odds");
}

export async function fetchHomepageBootstrap(): Promise<HomepageBootstrapResponse> {
  requireApiBase();
  return fetchJson<HomepageBootstrapResponse>(apiUrl("/homepage/bootstrap"), {}, "Homepage bootstrap");
}

export async function fetchLiveWithOdds(
  {
    perPage = 20,
    page = 1,
    search = "",
    leagues = [],
  }: OddsQueryOptions = {},
): Promise<PaginatedMatchesResponse<LiveMatchWithOdds>> {
  requireApiBase();
  const params = new URLSearchParams({
    per_page: String(perPage),
    page: String(page),
  });
  appendFilterParams(params, { search, leagues });
  const url = `${apiUrl("/pandascore/lol/live-with-odds")}?${params.toString()}`;
  return fetchJson<PaginatedMatchesResponse<LiveMatchWithOdds>>(url, {
    cache: "no-store",
  }, "Live with odds");
}

export async function fetchOddsRefreshStatus(): Promise<OddsRefreshStatus> {
  requireApiBase();
  return fetchJson<OddsRefreshStatus>(apiUrl("/pandascore/odds-refresh-status"), {
    cache: "no-store",
  }, "Odds refresh status");
}

export async function triggerOddsRefresh(): Promise<OddsRefreshAccepted | OddsRefreshLocked> {
  requireApiBase();
  const res = await fetch(apiUrl("/pandascore/refresh-odds"), {
    method: "POST",
    headers: apiHeaders(),
  });
  const payload = (await res.json().catch(() => null)) as
    | {
      status?: string;
      message?: string;
      task_ids?: string[];
      detail?: { message?: string; next_available_at?: string | null };
      next_available_at?: string | null;
    }
    | null;

  if (res.status === 429) {
    return {
      status: "locked",
      message:
        payload?.detail?.message ??
        payload?.message ??
        "Manual refresh is temporarily locked.",
      next_available_at:
        payload?.detail?.next_available_at ?? payload?.next_available_at ?? null,
    };
  }

  if (!res.ok) {
    throw new Error(
      `Odds refresh failed: ${res.status} ${JSON.stringify(payload).slice(0, 200)}`,
    );
  }

  return {
    status: "accepted",
    message: payload?.message ?? "Odds refresh started",
    task_ids: payload?.task_ids ?? [],
  };
}

export async function fetchOddsRefreshProgress(taskId: string): Promise<OddsRefreshProgress> {
  requireApiBase();
  const params = new URLSearchParams({ task_id: taskId });
  return fetchJson<OddsRefreshProgress>(`${apiUrl("/pandascore/refresh-odds-progress")}?${params.toString()}`, {
    cache: "no-store",
  }, "Odds refresh progress");
}

export async function fetchOddsRefreshGlobalStatus(): Promise<OddsRefreshGlobalStatus> {
  requireApiBase();
  return fetchJson<OddsRefreshGlobalStatus>(apiUrl("/pandascore/odds-refresh-global-status"), {
    cache: "no-store",
  }, "Odds refresh global status");
}

export async function fetchBettingHistory(
  {
    page = 1,
    perPage = 50,
    search = "",
    leagues = [],
  }: HistoryQueryOptions = {},
): Promise<PaginatedResponse<Result>> {
  requireApiBase();
  const params = new URLSearchParams({
    page: String(page),
    per_page: String(perPage),
  });
  appendFilterParams(params, { search, leagues });
  const url = `${apiUrl("/betting/results")}?${params.toString()}`;
  return fetchJson<PaginatedResponse<Result>>(url, {}, "Betting results");
}

export async function fetchResultsAnalytics(
  {
    search = "",
    leagues = [],
  }: HistoryQueryOptions = {},
): Promise<ResultsAnalytics> {
  requireApiBase();
  const params = new URLSearchParams();
  appendFilterParams(params, { search, leagues });
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return fetchJson<ResultsAnalytics>(`${apiUrl("/betting/results/analytics")}${suffix}`, {}, "Results analytics");
}

export async function fetchActiveBets(): Promise<ActiveBet[]> {
  requireApiBase();
  return fetchJson<ActiveBet[]>(apiUrl("/betting/bets/active"), {
    cache: "no-store",
  }, "Active bets");
}

export async function fetchOpenBetStatuses(): Promise<OpenBetScheduleStatus[]> {
  requireApiBase();
  return fetchJson<OpenBetScheduleStatus[]>(apiUrl("/betting/bets/open-status"), {
    cache: "no-store",
  }, "Open bet statuses");
}

export async function fetchBankrollSummary(): Promise<BankrollSummary> {
  requireApiBase();
  return fetchJson<BankrollSummary>(apiUrl("/betting/bankroll"), {}, "Bankroll summary");
}

export async function fetchPowerRankings(
  league?: string,
): Promise<PowerRankingRow[]> {
  requireApiBase();
  const params = new URLSearchParams();
  if (league && league !== "all") {
    params.set("league", league);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return fetchJson<PowerRankingRow[]>(`${apiUrl("/rankings/power")}${suffix}`, {}, "Power rankings");
}
