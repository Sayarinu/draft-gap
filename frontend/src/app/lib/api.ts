import type {
  LiveMatchWithOdds,
  PandaScoreUpcomingMatch,
  UpcomingMatchWithOdds,
} from "@/app/types/pandascore";
import type { ActiveBet, BankrollSummary } from "@/app/types/Betting";
import type { PowerRankingRow } from "@/app/types/PowerRanking";
import type { Result } from "@/app/types/Result";

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

const MISSING_API_URL_MESSAGE =
  "API URL is not set. Configure VITE_API_URL (or NEXT_PUBLIC_API_URL for compatibility) to your backend URL (e.g. http://localhost:8000).";

function readEnv(name: string): string {
  const viteValue = import.meta.env[name as keyof ImportMetaEnv];
  if (typeof viteValue === "string" && viteValue.length > 0) {
    return viteValue;
  }
  const processValue = (globalThis as { process?: { env?: Record<string, string | undefined> } })
    .process?.env?.[name];
  return processValue ?? "";
}

function getApiBaseUrl(): string {
  const env = readEnv("VITE_API_URL") || readEnv("NEXT_PUBLIC_API_URL");
  if (env) return env.replace(/\/$/, "");
  if (typeof window !== "undefined" && window.location?.hostname === "localhost") {
    return "http://localhost:8000";
  }
  if (typeof window !== "undefined") {
    return "";
  }
  return "";
}

function apiUrl(path: string): string {
  const base = getApiBaseUrl();
  const segment = path.startsWith("/") ? path : `/${path}`;
  if (base.endsWith("/api/v1")) {
    return `${base}${segment}`;
  }
  return `${base}/api/v1${segment}`;
}

function apiHeaders(extra: HeadersInit = {}): HeadersInit {
  const secret = readEnv("VITE_API_SECRET") || readEnv("NEXT_PUBLIC_API_SECRET");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (secret) headers["X-Api-Key"] = secret;
  return { ...headers, ...(extra as Record<string, string>) };
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

export async function fetchUpcomingMatches(
  perPage = 100,
  tier: string | null = "s,a",
): Promise<PandaScoreUpcomingMatch[]> {
  requireApiBase();
  const params = new URLSearchParams({ per_page: String(perPage) });
  if (tier) params.set("tier", tier);
  const url = `${apiUrl("/pandascore/lol/upcoming")}?${params.toString()}`;
  const res = await fetch(url, { headers: apiHeaders() });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(apiErrorMessage("Upcoming matches", res.status, text));
  }
  const data = (await res.json()) as PandaScoreUpcomingMatch[];
  return data;
}

export async function fetchUpcomingWithOdds(
  perPage = 100,
  tier: string | null = "s,a",
): Promise<UpcomingMatchWithOdds[]> {
  requireApiBase();
  const params = new URLSearchParams({ per_page: String(perPage) });
  if (tier) params.set("tier", tier);
  const url = `${apiUrl("/pandascore/lol/upcoming-with-odds")}?${params.toString()}`;
  const res = await fetch(url, { headers: apiHeaders() });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(apiErrorMessage("Upcoming with odds", res.status, text));
  }
  const data = (await res.json()) as UpcomingMatchWithOdds[];
  return data;
}

export async function fetchLiveWithOdds(
  perPage = 20,
): Promise<LiveMatchWithOdds[]> {
  requireApiBase();
  const params = new URLSearchParams({ per_page: String(perPage) });
  const url = `${apiUrl("/pandascore/lol/live-with-odds")}?${params.toString()}`;
  const res = await fetch(url, {
    headers: apiHeaders(),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(apiErrorMessage("Live with odds", res.status, text));
  }
  const data = (await res.json()) as LiveMatchWithOdds[];
  return data;
}

export async function fetchOddsRefreshStatus(): Promise<OddsRefreshStatus> {
  requireApiBase();
  const res = await fetch(apiUrl("/pandascore/odds-refresh-status"), {
    headers: apiHeaders(),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      apiErrorMessage("Odds refresh status", res.status, text),
    );
  }
  return (await res.json()) as OddsRefreshStatus;
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
  const res = await fetch(`${apiUrl("/pandascore/refresh-odds-progress")}?${params.toString()}`, {
    headers: apiHeaders(),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      apiErrorMessage("Odds refresh progress", res.status, text),
    );
  }
  return (await res.json()) as OddsRefreshProgress;
}

export async function fetchOddsRefreshGlobalStatus(): Promise<OddsRefreshGlobalStatus> {
  requireApiBase();
  const res = await fetch(apiUrl("/pandascore/odds-refresh-global-status"), {
    headers: apiHeaders(),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      apiErrorMessage("Odds refresh global status", res.status, text),
    );
  }
  return (await res.json()) as OddsRefreshGlobalStatus;
}

export async function fetchBettingResults(limit = 100): Promise<Result[]> {
  requireApiBase();
  const params = new URLSearchParams({ limit: String(limit) });
  const url = `${apiUrl("/betting/results")}?${params.toString()}`;
  const res = await fetch(url, { headers: apiHeaders() });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      apiErrorMessage("Betting results", res.status, text),
    );
  }
  return (await res.json()) as Result[];
}

export async function fetchActiveBets(): Promise<ActiveBet[]> {
  requireApiBase();
  const res = await fetch(apiUrl("/betting/bets/active"), {
    headers: apiHeaders(),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      apiErrorMessage("Active bets", res.status, text),
    );
  }
  return (await res.json()) as ActiveBet[];
}

export async function fetchBankrollSummary(): Promise<BankrollSummary> {
  requireApiBase();
  const res = await fetch(apiUrl("/betting/bankroll"), {
    headers: apiHeaders(),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      apiErrorMessage("Bankroll summary", res.status, text),
    );
  }
  return (await res.json()) as BankrollSummary;
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
  const res = await fetch(`${apiUrl("/rankings/power")}${suffix}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      apiErrorMessage("Power rankings", res.status, text),
    );
  }
  return (await res.json()) as PowerRankingRow[];
}
