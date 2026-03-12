export interface Bet {
  id: string;
  matchId: string;
  gameDateTime: string;
  league: string;
  team1: string;
  team2: string;
  team1ModelOdds: number;
  team1BookieOdds: number;
  team2ModelOdds: number;
  team2BookieOdds: number;
  betOn: string;
  lockedOdds: number;
  stake: number;
}
