export interface ActiveBet {
  id: string;
  pandascore_match_id: number;
  bet_on: string;
  locked_odds: number;
  stake: number;
}

export interface BankrollSummary {
  bankroll_id: string;
  name: string;
  currency: string;
  initial_balance: number;
  current_balance: number;
  active_bets: number;
  settled_bets: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  total_staked: number;
  total_profit_loss: number;
  roi_pct: number;
  peak_balance: number;
  drawdown_pct: number;
}
