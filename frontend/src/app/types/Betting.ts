export interface ActiveBet {
  id?: string | null;
  pandascore_match_id: number;
  series_key?: string | null;
  bet_sequence?: number | null;
  team_a?: string | null;
  team_b?: string | null;
  bet_on: string;
  market_type?: string | null;
  selection_key?: string | null;
  line_value?: number | null;
  source_market_name?: string | null;
  source_selection_name?: string | null;
  locked_odds: number;
  stake: number;
  status?: string | null;
  league?: string | null;
  entry_phase?: string | null;
  entry_score_team_a?: number | null;
  entry_score_team_b?: number | null;
  current_score_team_a?: number | null;
  current_score_team_b?: number | null;
  odds_source_status?: string | null;
  feed_health_status?: string | null;
  placed_at?: string | null;
}

export interface ActiveSeriesPositionGroup {
  series_key: string;
  pandascore_match_id: number;
  team_a: string;
  team_b: string;
  league: string | null;
  position_count: number;
  total_exposure: number;
  team_stake_totals: Record<string, number>;
  net_side?: string | null;
  net_stake_delta: number;
  has_conflicting_positions: boolean;
  single_position_summary?: {
    label: string;
    side: string;
    locked_odds: number;
    stake: number;
  };
  multi_position_summary?: {
    label: string;
    bet_count: number;
    team_a_stake: number;
    team_b_stake: number;
    team_a_label: string;
    team_b_label: string;
    net_side?: string | null;
    net_stake_delta: number;
  };
  latest_position: ActiveBet;
  positions: ActiveBet[];
}

export type MatchBettingStatusType =
  | "placed"
  | "pending_auto_bet"
  | "pending_force_bet"
  | "waiting_for_better_odds"
  | "blocked_missing_odds"
  | "blocked_team_resolution_failed"
  | "blocked_model_unavailable"
  | "blocked_prediction_unavailable"
  | "blocked_low_confidence"
  | "blocked_low_ev"
  | "blocked_invalid_odds"
  | "blocked_invalid_line"
  | "blocked_unsupported_market"
  | "blocked_tbd"
  | "blocked_invalid_stake"
  | "blocked_league_not_bettable"
  | "blocked_tier_not_bettable"
  | "blocked_status_generation_failed";

export interface MatchBettingStatus {
  pandascore_match_id: number;
  series_key?: string;
  status: MatchBettingStatusType;
  bet_on?: string;
  market_type?: string;
  selection_key?: string;
  line_value?: number | null;
  locked_odds?: number;
  stake?: number;
  position_count?: number;
  reason_code?: string | null;
  short_detail?: string | null;
  within_force_window?: boolean;
  force_bet_after?: string | null;
  is_bettable?: boolean;
  eligibility_reason?: string | null;
  normalized_identity?: string | null;
  odds_source_kind?: string | null;
  odds_source_status?: string | null;
  market_offer_count?: number;
  has_match_winner_offer?: boolean;
  terminal_outcome?: string | null;
  series_decision_context?: Record<string, unknown>;
}

export interface OpenBetScheduleStatus {
  id: string;
  pandascore_match_id: number;
  team_a: string;
  team_b: string;
  bet_on: string;
  market_type: string;
  selection_key: string;
  line_value?: number | null;
  locked_odds: number;
  stake: number;
  schedule_status:
    | "scheduled_upcoming"
    | "scheduled_live"
    | "completed_pending_settlement"
    | "cancelled"
    | "missing_from_feed";
  league: string | null;
  model_run_id: number | null;
  series_key: string;
  bet_sequence: number;
}

export interface BankrollSummary {
  initial_balance: number;
  current_balance: number;
  win_rate_pct: number;
  total_profit: number;
  roi_pct: number;
}
