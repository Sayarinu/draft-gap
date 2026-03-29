export interface Result {
  id: string;
  betDateTime: string;
  league: string;
  team1: string;
  team2: string;
  betOn: string;
  lockedOdds: number;
  stake: number;
  result: "WON" | "LOST";
  profit: number;
}

export interface ResultsSummary {
  wins: number;
  losses: number;
  settled: number;
  total_staked: number;
  total_profit: number;
  win_rate: number;
  roi: number;
}

export interface ResultsCumulativePoint {
  label: string;
  profit: number;
}

export interface ResultsOutcomeDatum {
  name: string;
  value: number;
}

export interface ResultsLeagueProfitDatum {
  league: string;
  profit: number;
}

export interface ResultsAnalytics {
  summary: ResultsSummary;
  cumulative_profit_data: ResultsCumulativePoint[];
  outcome_data: ResultsOutcomeDatum[];
  league_profit_data: ResultsLeagueProfitDatum[];
  available_leagues: string[];
}
