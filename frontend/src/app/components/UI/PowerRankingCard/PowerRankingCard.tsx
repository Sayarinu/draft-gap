"use client";

import type { PowerRankingRow } from "@/app/types/PowerRanking";

interface PowerRankingCardProps {
  row: PowerRankingRow;
}

function formatPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function winRateColor(value: number): string {
  if (value >= 0.65) return "text-safe";
  if (value >= 0.5) return "text-gold";
  return "text-error";
}

export const PowerRankingCard = ({ row }: PowerRankingCardProps) => {
  const gd15 = row.avg_gold_diff_15;
  const gd15Rounded = Number(gd15.toFixed(0));
  const gd15Color = gd15 >= 0 ? "text-safe" : "text-error";
  const gd15Sign = gd15 > 0 ? "+" : "";

  return (
    <article className="flex items-center justify-between gap-3 border-b border-concrete bg-deepdark px-4 py-3 last:border-b-0">
      <div className="flex min-w-0 shrink-0 items-center gap-3">
        <span className="font-mono text-sm font-bold text-gold">#{row.rank}</span>
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-cream">{row.team}</div>
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-0.5">
        <span className="text-2xs font-semibold uppercase tracking-wide text-taupe">
          {row.league_slug}
        </span>
        <span className="font-mono text-sm text-cream">
          {row.wins}-{row.losses}
        </span>
        <span
          className={`font-mono text-sm font-semibold ${winRateColor(row.win_rate)}`}
        >
          {formatPct(row.win_rate)}
        </span>
        {gd15Rounded !== 0 && (
          <span className={`font-mono text-2xs font-semibold ${gd15Color}`}>
            GD@15 {gd15Sign}
            {gd15Rounded}
          </span>
        )}
      </div>
    </article>
  );
};
