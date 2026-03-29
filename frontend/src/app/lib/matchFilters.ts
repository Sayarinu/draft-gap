import type { LiveMatchWithOdds, UpcomingMatchWithOdds } from "@/app/types/pandascore";
import type { Result } from "@/app/types/Result";

export function getLeagueName(m: UpcomingMatchWithOdds | LiveMatchWithOdds): string {
  return m.league_name.trim();
}

export function matchesSearch(
  m: UpcomingMatchWithOdds | LiveMatchWithOdds,
  query: string,
): boolean {
  if (!query) return true;
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const league = m.league_name.toLowerCase();
  const haystack = [
    league,
    m.team1_name.toLowerCase(),
    m.team2_name.toLowerCase(),
    (m.team1_acronym ?? "").toLowerCase(),
    (m.team2_acronym ?? "").toLowerCase(),
  ];
  return haystack.some((s) => s.includes(q));
}

export function isTbdVsTbd(m: UpcomingMatchWithOdds | LiveMatchWithOdds): boolean {
  const a = m.team1_name.trim().toUpperCase() || "TBD";
  const b = m.team2_name.trim().toUpperCase() || "TBD";
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
