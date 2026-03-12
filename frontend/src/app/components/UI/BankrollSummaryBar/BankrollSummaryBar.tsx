"use client";

import { useEffect, useState } from "react";

import { fetchBankrollSummary } from "@/app/lib/api";
import type { BankrollSummary } from "@/app/types/Betting";

const formatCurrency = (value: number): string => `$${value.toFixed(2)}`;

interface BankrollSummaryBarProps {
  refreshKey?: number;
  isRefreshing?: boolean;
}

export const BankrollSummaryBar = ({ refreshKey, isRefreshing }: BankrollSummaryBarProps) => {
  const [summary, setSummary] = useState<BankrollSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    const run = () => {
      fetchBankrollSummary()
        .then((next) => {
          if (!cancelled) setSummary(next);
        })
        .catch(() => {
          if (!cancelled) setSummary(null);
        });
    };
    run();
    const id = setInterval(run, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [refreshKey, isRefreshing]);

  if (!summary) {
    return (
      <section className="w-full border-b border-coffee bg-deepdark p-4 text-xs text-taupe">
        LOADING BANKROLL...
      </section>
    );
  }

  const changePct = summary.initial_balance > 0
    ? ((summary.current_balance - summary.initial_balance) / summary.initial_balance) * 100
    : 0;
  const changeColor = changePct >= 0 ? "text-safe" : "text-error";
  const drawdownAlert = summary.drawdown_pct >= 25;

  return (
    <section className="border-b border-coffee bg-deepdark px-4 py-2">
      <div className="flex flex-wrap items-center gap-4 text-xs uppercase tracking-wide">
        <span className="text-gold font-bold tracking-widest">Bankroll</span>
        <span className="text-taupe">Balance <span className="font-mono text-cream">{formatCurrency(summary.current_balance)}</span></span>
        <span className="text-taupe" title="Percentage change from your starting (initial) bankroll">
          CHANGE <span className={`font-mono ${changeColor}`}>{changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%</span>
        </span>
        <span className="text-taupe">Active Bets <span className="font-mono text-cream">{summary.active_bets}</span></span>
        <span className="text-taupe">Win Rate <span className="font-mono text-cream">{summary.win_rate_pct.toFixed(1)}%</span></span>
        <span className="text-taupe">ROI <span className={`font-mono ${summary.roi_pct >= 0 ? "text-safe" : "text-error"}`}>{summary.roi_pct >= 0 ? "+" : ""}{summary.roi_pct.toFixed(2)}%</span></span>
        {drawdownAlert && (
          <span className="rounded border border-error/60 bg-error/10 px-2 py-0.5 text-2xs text-error">
            Drawdown {summary.drawdown_pct.toFixed(1)}%
          </span>
        )}
      </div>
    </section>
  );
};
