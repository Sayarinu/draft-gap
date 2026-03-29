export interface OddsMatchBase {
  id: number;
  scheduled_at: string;
  league_name: string;
  team1_name: string;
  team1_acronym: string | null;
  team2_name: string;
  team2_acronym: string | null;
  stream_url: string | null;
  bookie_odds_team1: number | null;
  bookie_odds_team2: number | null;
  bookie_odds_status_team1?: string | null;
  bookie_odds_status_team2?: string | null;
  model_odds_team1: number | null;
  model_odds_team2: number | null;
  series_format: "BO1" | "BO3" | "BO5";
  markets: Array<{
    market_type: string;
    selection_key: string;
    line_value: number | null;
    decimal_odds: number | null;
    market_status: string;
    source_market_name?: string | null;
    source_selection_name?: string | null;
  }>;
  recommended_bet?: {
    market_type: string;
    selection_key: string;
    line_value: number | null;
    bet_on: string;
    locked_odds: number;
    edge: number;
    stake: number;
  } | null;
}

export type UpcomingMatchWithOdds = OddsMatchBase;

export interface LiveMatchWithOdds extends OddsMatchBase {
  series_score_team1: number;
  series_score_team2: number;
  pre_match_odds_team1: number | null;
  pre_match_odds_team2: number | null;
  live_recommendation?: {
    rebet_allowed?: boolean;
    confidence?: number;
    base_game_win_prob_a?: number;
    adjusted_game_win_prob_a?: number;
    series_win_prob_a?: number;
    series_win_prob_b?: number;
    mid_series_delta?: number;
    edge_vs_market_team1?: number | null;
    edge_vs_market_team2?: number | null;
    incremental_ev_team1?: number | null;
    incremental_ev_team2?: number | null;
  } | null;
}

export interface PaginatedResponse<TItem> {
  items: TItem[];
  page: number;
  per_page: number;
  total_items: number;
  total_pages: number;
  available_leagues?: string[];
}

export type PaginatedMatchesResponse<TItem> = PaginatedResponse<TItem>;
