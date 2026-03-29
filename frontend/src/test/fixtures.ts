import type { BankrollSummary } from "@/app/types/Betting";
import type { PowerRankingRow } from "@/app/types/PowerRanking";
import type { Result, ResultsAnalytics } from "@/app/types/Result";
import type {
  PaginatedResponse,
  LiveMatchWithOdds,
  PaginatedMatchesResponse,
  UpcomingMatchWithOdds,
} from "@/app/types/pandascore";

export const upcomingMatchesFixture: UpcomingMatchWithOdds[] = [
  {
    id: 1001,
    scheduled_at: "2026-03-22T18:00:00Z",
    league_name: "LCK",
    team1_name: "Alpha",
    team1_acronym: "ALP",
    team2_name: "Beta",
    team2_acronym: "BET",
    stream_url: null,
    bookie_odds_team1: 2.2,
    bookie_odds_team2: 1.7,
    model_odds_team1: 1.9,
    model_odds_team2: 2.05,
    series_format: "BO3",
    markets: [],
  },
  {
    id: 1002,
    scheduled_at: "2026-03-22T20:00:00Z",
    league_name: "LEC",
    team1_name: "Delta",
    team1_acronym: "DLT",
    team2_name: "Echo",
    team2_acronym: "ECH",
    stream_url: null,
    bookie_odds_team1: 1.8,
    bookie_odds_team2: 2.1,
    model_odds_team1: 1.7,
    model_odds_team2: 2.2,
    series_format: "BO1",
    markets: [],
  },
];

export const upcomingPaginatedFixture: PaginatedMatchesResponse<UpcomingMatchWithOdds> = {
  items: upcomingMatchesFixture,
  page: 1,
  per_page: 10,
  total_items: 12,
  total_pages: 2,
  available_leagues: ["LCK", "LEC"],
};

export const liveMatchesFixture: LiveMatchWithOdds[] = [
  {
    ...upcomingMatchesFixture[0],
    stream_url: "https://player.example.com/alpha-beta",
    bookie_odds_status_team1: "available",
    bookie_odds_status_team2: "available",
    series_score_team1: 1,
    series_score_team2: 0,
    pre_match_odds_team1: 2.1,
    pre_match_odds_team2: 1.8,
    live_recommendation: {
      rebet_allowed: true,
      confidence: 0.71,
      base_game_win_prob_a: 0.53,
      adjusted_game_win_prob_a: 0.58,
      series_win_prob_a: 0.66,
      series_win_prob_b: 0.34,
      mid_series_delta: 0.05,
      edge_vs_market_team1: 0.04,
      edge_vs_market_team2: -0.04,
      incremental_ev_team1: 0.09,
      incremental_ev_team2: -0.08,
    },
  },
];

export const livePaginatedFixture: PaginatedMatchesResponse<LiveMatchWithOdds> = {
  items: liveMatchesFixture,
  page: 1,
  per_page: 20,
  total_items: 1,
  total_pages: 1,
  available_leagues: ["LCK"],
};

export const resultsFixture: Result[] = [
  {
    id: "result-1",
    betDateTime: "2026-03-22T12:00:00Z",
    league: "LCK",
    team1: "Alpha",
    team2: "Beta",
    betOn: "Alpha",
    lockedOdds: 2.2,
    stake: 50,
    result: "WON",
    profit: 60,
  },
  {
    id: "result-2",
    betDateTime: "2026-03-22T13:00:00Z",
    league: "LEC",
    team1: "Delta",
    team2: "Echo",
    betOn: "Echo",
    lockedOdds: 2.1,
    stake: 25,
    result: "LOST",
    profit: -25,
  },
];

export const resultsHistoryFixture: PaginatedResponse<Result> = {
  items: resultsFixture,
  page: 1,
  per_page: 25,
  total_items: 2,
  total_pages: 1,
  available_leagues: ["LCK", "LEC"],
};

export const resultsAnalyticsFixture: ResultsAnalytics = {
  summary: {
    wins: 1,
    losses: 1,
    settled: 2,
    total_staked: 75,
    total_profit: 35,
    win_rate: 50,
    roi: 46.67,
  },
  cumulative_profit_data: [
    { label: "3/22", profit: 60 },
    { label: "3/22", profit: 35 },
  ],
  outcome_data: [
    { name: "Won", value: 1 },
    { name: "Lost", value: 1 },
  ],
  league_profit_data: [
    { league: "LCK", profit: 60 },
    { league: "LEC", profit: -25 },
  ],
  available_leagues: ["LCK", "LEC"],
};

export const bankrollSummaryFixture: BankrollSummary = {
  initial_balance: 1000,
  current_balance: 1110,
  win_rate_pct: 60,
  total_profit: 110,
  roi_pct: 44,
};

export const activeBetsFixture = [
  {
    id: "bet-1",
    pandascore_match_id: 1001,
    series_key: "ps:1001",
    bet_sequence: 1,
    team_a: "Alpha",
    team_b: "Beta",
    bet_on: "Alpha",
    locked_odds: 2.2,
    stake: 50,
    status: "LIVE",
    entry_phase: "prematch",
    entry_score_team_a: 0,
    entry_score_team_b: 0,
    current_score_team_a: 1,
    current_score_team_b: 0,
    odds_source_status: "available",
    feed_health_status: "tracked",
    placed_at: "2026-03-22T16:00:00Z",
  },
];

export const activePositionsBySeriesFixture = [
  {
    series_key: "ps:1001",
    pandascore_match_id: 1001,
    team_a: "Alpha",
    team_b: "Beta",
    league: "LCK",
    position_count: 1,
    total_exposure: 50,
    team_stake_totals: { Alpha: 50, Beta: 0 },
    net_side: "Alpha",
    net_stake_delta: 50,
    has_conflicting_positions: false,
    single_position_summary: {
      label: "Bet: Alpha @ 2.20",
      side: "Alpha",
      locked_odds: 2.2,
      stake: 50,
    },
    multi_position_summary: {
      label: "1 bet",
      bet_count: 1,
      team_a_stake: 50,
      team_b_stake: 0,
      team_a_label: "Alpha",
      team_b_label: "Beta",
      net_side: "Alpha",
      net_stake_delta: 50,
    },
    latest_position: activeBetsFixture[0],
    positions: activeBetsFixture,
  },
];

export const matchBettingStatusesFixture = [
  {
    pandascore_match_id: 1001,
    series_key: "ps:1001",
    status: "placed" as const,
    bet_on: "Alpha",
    locked_odds: 2.2,
    stake: 50,
    position_count: 1,
  },
  {
    pandascore_match_id: 1002,
    status: "waiting_for_better_odds" as const,
    force_bet_after: "2026-03-22T16:00:00Z",
  },
  {
    pandascore_match_id: 1003,
    status: "blocked_missing_odds" as const,
    reason_code: "missing_bookie_odds",
    short_detail: "NO THUNDERPICK MATCH",
    within_force_window: true,
    force_bet_after: "2026-03-22T16:00:00Z",
  },
  {
    pandascore_match_id: 1004,
    status: "pending_force_bet" as const,
    reason_code: "eligible_force_bet",
    within_force_window: true,
    force_bet_after: "2026-03-22T16:00:00Z",
  },
];

export const oddsRefreshGlobalStatusFixture = {
  in_progress: false,
  task_id: null,
  progress: 0,
  stage: "",
  last_completed_at: "2026-03-22T17:45:00Z",
  next_scheduled_at: "2026-03-22T17:50:00Z",
};

export const powerRankingsPreviewFixture: PowerRankingRow[] = [
  {
    rank: 1,
    team: "Preview Prime",
    league_slug: "lck",
    wins: 12,
    losses: 3,
    win_rate: 0.8,
    avg_game_duration_min: 31.2,
    avg_gold_diff_15: 845,
    first_blood_pct: 0.62,
    first_dragon_pct: 0.7,
    first_tower_pct: 0.66,
    games_played: 15,
  },
];

export const powerRankingsFixture: PowerRankingRow[] = [
  {
    rank: 1,
    team: "Full Power",
    league_slug: "lpl",
    wins: 18,
    losses: 2,
    win_rate: 0.9,
    avg_game_duration_min: 30.4,
    avg_gold_diff_15: 912,
    first_blood_pct: 0.68,
    first_dragon_pct: 0.74,
    first_tower_pct: 0.71,
    games_played: 20,
  },
  {
    rank: 2,
    team: "Mid Lane State",
    league_slug: "lck",
    wins: 16,
    losses: 4,
    win_rate: 0.8,
    avg_game_duration_min: 31.8,
    avg_gold_diff_15: 640,
    first_blood_pct: 0.59,
    first_dragon_pct: 0.67,
    first_tower_pct: 0.65,
    games_played: 20,
  },
];

export const homepageBootstrapFixture = {
  generated_at: "2026-03-22T17:45:00Z",
  results_generated_at: "2026-03-22T17:45:00Z",
  upcoming: upcomingPaginatedFixture,
  live: livePaginatedFixture,
  bankroll: bankrollSummaryFixture,
  active_bets: activeBetsFixture,
  active_positions_by_series: activePositionsBySeriesFixture,
  match_betting_statuses: matchBettingStatusesFixture,
  power_rankings_preview: powerRankingsPreviewFixture,
  refresh_status: {
    in_progress: oddsRefreshGlobalStatusFixture.in_progress,
    progress: oddsRefreshGlobalStatusFixture.progress,
    stage: oddsRefreshGlobalStatusFixture.stage,
    last_completed_at: oddsRefreshGlobalStatusFixture.last_completed_at,
    next_scheduled_at: oddsRefreshGlobalStatusFixture.next_scheduled_at,
  },
  section_status: {
    homepage: {
      generated_at: "2026-03-22T17:45:00Z",
      data_as_of: "2026-03-22T17:45:00Z",
      snapshot_version: "homepage-test",
      is_stale: false,
      status: "success",
      source: "snapshot",
    },
    upcoming: {
      generated_at: "2026-03-22T17:45:00Z",
      data_as_of: "2026-03-22T17:45:00Z",
      snapshot_version: "upcoming-test",
      is_stale: false,
      status: "success",
      source: "snapshot",
    },
    live: {
      generated_at: "2026-03-22T17:45:00Z",
      data_as_of: "2026-03-22T17:45:00Z",
      snapshot_version: "live-test",
      is_stale: false,
      status: "success",
      source: "snapshot",
    },
  },
};
