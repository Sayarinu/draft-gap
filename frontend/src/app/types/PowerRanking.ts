export interface PowerRankingRow {
  rank: number;
  team: string;
  abbreviation: string | null;
  league: string;
  league_slug: string;
  wins: number;
  losses: number;
  win_rate: number;
  avg_game_duration_min: number;
  avg_gold_diff_15: number;
  first_blood_pct: number;
  first_dragon_pct: number;
  first_tower_pct: number;
  kda: number;
  games_played: number;
  playoff_games: number;
  playoff_wins: number;
  playoff_losses: number;
  split_titles: number;
  strength_of_schedule: number;
  region_weight: number;
  composite_score: number;
}
