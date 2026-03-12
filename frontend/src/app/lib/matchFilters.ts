import type { LiveMatchWithOdds, UpcomingMatchWithOdds } from "@/app/types/pandascore";
import type { Result } from "@/app/types/Result";

export function getLeagueName(m: UpcomingMatchWithOdds | LiveMatchWithOdds): string {
  return m.league?.name?.trim() ?? "";
}

export function matchesSearch(
  m: UpcomingMatchWithOdds | LiveMatchWithOdds,
  query: string,
): boolean {
  if (!query) return true;
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const league = m.league?.name?.toLowerCase() ?? "";
  const haystack = [
    league,
    ...m.opponents.map((o) => o.opponent?.name?.toLowerCase() ?? ""),
    ...m.opponents.map((o) => o.opponent?.acronym?.toLowerCase() ?? ""),
  ];
  return haystack.some((s) => s.includes(q));
}

export function isTbdVsTbd(m: UpcomingMatchWithOdds | LiveMatchWithOdds): boolean {
  const a = m.opponents[0]?.opponent?.name?.trim().toUpperCase() ?? "TBD";
  const b = m.opponents[1]?.opponent?.name?.trim().toUpperCase() ?? "TBD";
  return a === "TBD" && b === "TBD";
}

export function getResultLeagueName(r: Result): string {
  return r.league?.trim() ?? "";
}

export function matchesResultSearch(r: Result, query: string): boolean {
  if (!query) return true;
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [r.league, r.team1, r.team2, r.betOn]
    .map((part) => part.toLowerCase())
    .some((part) => part.includes(q));
}
