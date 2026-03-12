export interface PandaScoreOpponent {
  id: number;
  name: string;
  location: string | null;
  slug: string;
  acronym: string | null;
  image_url: string | null;
  dark_mode_image_url?: string | null;
}

export interface PandaScoreOpponentSlot {
  type: string;
  opponent: PandaScoreOpponent;
}

export interface PandaScoreLeague {
  id: number;
  name: string;
  slug: string;
  image_url: string | null;
}

export interface PandaScoreTournament {
  id: number;
  name: string;
  type: string;
  country: string | null;
  tier?: string;
  region?: string | null;
  begin_at: string;
  end_at: string | null;
}

export interface PandaScoreStream {
  main: boolean;
  language: string;
  raw_url: string;
  embed_url?: string;
  official?: boolean;
}

export interface PandaScoreMatchResult {
  team_id: number;
  score: number;
}

export interface PandaScoreUpcomingMatch {
  id: number;
  name: string;
  status: string;
  scheduled_at: string;
  begin_at: string | null;
  end_at: string | null;
  original_scheduled_at: string;
  modified_at: string;
  league_id: number;
  league: PandaScoreLeague;
  tournament_id?: number;
  tournament?: PandaScoreTournament;
  opponents: PandaScoreOpponentSlot[];
  results: PandaScoreMatchResult[];
  number_of_games: number;
  match_type: string;
  streams_list: PandaScoreStream[];
  live?: { supported: boolean; url: string | null; opens_at: string | null };
  forfeit: boolean;
  draw: boolean;
  winner_id: number | null;
  winner: unknown;
}

export interface UpcomingMatchWithOdds extends PandaScoreUpcomingMatch {
  bookie_odds_team1: number | null;
  bookie_odds_team2: number | null;
  model_odds_team1: number | null;
  model_odds_team2: number | null;
  series_format?: "BO1" | "BO3" | "BO5";
}

export interface LiveMatchWithOdds extends UpcomingMatchWithOdds {
  series_score_team1: number;
  series_score_team2: number;
  series_format: "BO1" | "BO3" | "BO5";
  pre_match_odds_team1: number | null;
  pre_match_odds_team2: number | null;
}
