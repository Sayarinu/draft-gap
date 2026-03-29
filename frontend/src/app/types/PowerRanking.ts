export interface PowerRankingRow {
  rank: number;
  team: string;
  league_slug: string;
  wins: number;
  losses: number;
  win_rate: number;
  avg_game_duration_min: number;
  avg_gold_diff_15: number;
  first_blood_pct: number;
  first_dragon_pct: number;
  first_tower_pct: number;
  games_played: number;
}
