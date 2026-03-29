"use client";

import type { BankrollSummary } from "@/app/types/Betting";

const formatCurrency = (value: number): string => `$${value.toFixed(2)}`;

interface BankrollSummaryBarProps {
  summary?: BankrollSummary | null;
}

export const BankrollSummaryBar = ({ summary = null }: BankrollSummaryBarProps) => {
  if (!summary) {
    return (
      <section className="w-full border-b border-coffee bg-deepdark p-4 text-xs text-taupe">
        LOADING BANKROLL...
      </section>
    );
  }

  return (
    <section className="border-b border-coffee bg-deepdark px-4 py-2">
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-2xs uppercase tracking-wide sm:flex sm:flex-wrap sm:items-center sm:gap-4 sm:text-xs">
        <span className="col-span-2 font-bold tracking-widest text-gold sm:col-auto">Bankroll</span>
        <span className="text-taupe">Balance <span className="font-mono text-cream">{formatCurrency(summary.current_balance)}</span></span>
        <span className="text-taupe">Win Rate <span className="font-mono text-cream">{summary.win_rate_pct.toFixed(1)}%</span></span>
        <span className="text-taupe">ROI <span className={`font-mono ${summary.roi_pct >= 0 ? "text-safe" : "text-error"}`}>{summary.roi_pct >= 0 ? "+" : ""}{summary.roi_pct.toFixed(2)}%</span></span>
        <span className="text-taupe">Profit <span className={`font-mono ${summary.total_profit >= 0 ? "text-safe" : "text-error"}`}>{formatCurrency(summary.total_profit)}</span></span>
      </div>
    </section>
  );
};
