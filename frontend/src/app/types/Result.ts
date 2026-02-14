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
  profitLoss: number;
}
