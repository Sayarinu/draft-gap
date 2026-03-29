import type { ActiveBet } from "@/app/types/Betting";
import type {
  LiveMatchWithOdds,
  UpcomingMatchWithOdds,
} from "@/app/types/pandascore";

type MatchWithOdds = UpcomingMatchWithOdds | LiveMatchWithOdds;

export const POSITIVE_EDGE_THRESHOLD = 0.03;

export const formatDecimalOdds = (value: number | null | undefined): string => {
  if (value == null || value <= 0 || Number.isNaN(value)) {
    return "—";
  }
  return value.toFixed(2);
};

export const getTeamName = (
  match: MatchWithOdds,
  team: 1 | 2,
): string => {
  const opponent = team === 1 ? match.team1_name : match.team2_name;
  return opponent.trim() || "TBD";
};

export const getTeamAcronym = (
  match: MatchWithOdds,
  team: 1 | 2,
): string => {
  const acronym = team === 1 ? match.team1_acronym : match.team2_acronym;
  return (acronym ?? "").toUpperCase();
};

export const normalizeTeamName = (value: string): string => {
  return value.trim().toUpperCase().replace(/\s+/g, " ");
};

export const isBetOnTeam = (
  activeBet: ActiveBet | undefined | null,
  teamName: string,
): boolean => {
  if (!activeBet) {
    return false;
  }
  return normalizeTeamName(activeBet.bet_on) === normalizeTeamName(teamName);
};

export const getEdge = (
  match: MatchWithOdds,
  team: 1 | 2,
): number | null => {
  const modelOdds = team === 1 ? match.model_odds_team1 : match.model_odds_team2;
  const bookOddsTeam1 = match.bookie_odds_team1;
  const bookOddsTeam2 = match.bookie_odds_team2;

  if (
    modelOdds == null ||
    bookOddsTeam1 == null ||
    bookOddsTeam2 == null ||
    modelOdds <= 0 ||
    bookOddsTeam1 <= 0 ||
    bookOddsTeam2 <= 0
  ) {
    return null;
  }

  const impliedTeam1 = 1 / bookOddsTeam1;
  const impliedTeam2 = 1 / bookOddsTeam2;
  const impliedTotal = impliedTeam1 + impliedTeam2;
  if (impliedTotal <= 0) {
    return null;
  }

  const adjustedBookProbability =
    team === 1 ? impliedTeam1 / impliedTotal : impliedTeam2 / impliedTotal;
  const modelProbability = 1 / modelOdds;
  return modelProbability - adjustedBookProbability;
};

export const hasPositiveEdge = (edge: number | null): boolean => {
  return edge != null && edge > POSITIVE_EDGE_THRESHOLD;
};
