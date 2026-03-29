"use client";

import type { MatchBettingStatus } from "@/app/types/Betting";

export function getMatchStatusLabel(matchBettingStatus?: MatchBettingStatus | null): string | null {
  switch (matchBettingStatus?.status) {
    case "pending_auto_bet":
      return "PENDING · AUTO BET";
    case "pending_force_bet":
      return "PENDING · FORCE BET";
    case "waiting_for_better_odds":
      return "WAITING · BETTER PRICE";
    case "blocked_missing_odds":
      return "BLOCKED · NO ODDS";
    case "blocked_team_resolution_failed":
      return "BLOCKED · TEAM MATCH";
    case "blocked_model_unavailable":
      return "BLOCKED · MODEL OFFLINE";
    case "blocked_prediction_unavailable":
      return "BLOCKED · NO PREDICTION";
    case "blocked_low_confidence":
      return "BLOCKED · LOW CONFIDENCE";
    case "blocked_low_ev":
      return "BLOCKED · LOW EV";
    case "blocked_invalid_odds":
      return "BLOCKED · INVALID ODDS";
    case "blocked_invalid_line":
      return "BLOCKED · INVALID LINE";
    case "blocked_unsupported_market":
      return "BLOCKED · MARKET";
    case "blocked_tbd":
      return "BLOCKED · TBD TEAM";
    case "blocked_invalid_stake":
      return "BLOCKED · STAKE";
    case "blocked_league_not_bettable":
      return "BLOCKED · LEAGUE";
    case "blocked_tier_not_bettable":
      return "BLOCKED · TIER";
    case "blocked_status_generation_failed":
      return "BLOCKED · STATUS";
    default:
      return null;
  }
}

export function getMatchStatusDetail(matchBettingStatus?: MatchBettingStatus | null): string | null {
  const shortDetail = matchBettingStatus?.short_detail?.trim();
  if (shortDetail) return shortDetail;
  return null;
}
