"use client";

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Result } from "@/app/types/Result";

interface ResultsMetricsProps {
  results: Result[];
}

const formatCurrency = (value: number): string => {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
};

const formatPercent = (value: number): string =>
  `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;

const CHART_COLORS = {
  won: "var(--color-safe)",
  lost: "var(--color-error)",
  void: "var(--color-stone)",
  pnl: "var(--color-gold)",
};

export const ResultsMetrics = ({ results }: ResultsMetricsProps) => {
  const summary = useMemo(() => {
    let wins = 0;
    let losses = 0;
    let voids = 0;
    let totalStaked = 0;
    let totalPnl = 0;

    results.forEach((row) => {
      totalStaked += row.stake;
      totalPnl += row.profitLoss;
      if (row.result === "WON") wins += 1;
      else if (row.result === "LOST") losses += 1;
      else voids += 1;
    });

    const settled = wins + losses + voids;
    const winRate = settled > 0 ? (wins / settled) * 100 : 0;
    const roi = totalStaked > 0 ? (totalPnl / totalStaked) * 100 : 0;

    return {
      wins,
      losses,
      voids,
      settled,
      totalStaked,
      totalPnl,
      winRate,
      roi,
    };
  }, [results]);

  const cumulativePnlData = useMemo(() => {
    const sorted = [...results].sort(
      (a, b) =>
        new Date(a.betDateTime).getTime() - new Date(b.betDateTime).getTime(),
    );
    return sorted.reduce<Array<{ label: string; pnl: number }>>((acc, row) => {
      const previousPnl = acc.length === 0 ? 0 : acc[acc.length - 1].pnl;
      const nextPnl = Number((previousPnl + row.profitLoss).toFixed(2));
      const date = new Date(row.betDateTime);
      return [
        ...acc,
        {
        label: date.toLocaleDateString(undefined, {
          month: "numeric",
          day: "numeric",
        }),
          pnl: nextPnl,
        },
      ];
    }, []);
  }, [results]);

  const outcomeData = useMemo(
    () => [
      { name: "Won", value: summary.wins, color: CHART_COLORS.won },
      { name: "Lost", value: summary.losses, color: CHART_COLORS.lost },
      { name: "Void", value: summary.voids, color: CHART_COLORS.void },
    ],
    [summary.losses, summary.voids, summary.wins],
  );

  const leaguePnlData = useMemo(() => {
    const byLeague = new Map<string, number>();
    results.forEach((row) => {
      byLeague.set(row.league, (byLeague.get(row.league) ?? 0) + row.profitLoss);
    });
    return Array.from(byLeague.entries())
      .map(([league, pnl]) => ({ league, pnl: Number(pnl.toFixed(2)) }))
      .sort((a, b) => b.pnl - a.pnl)
      .slice(0, 10);
  }, [results]);

  if (results.length === 0) return null;

  return (
    <section className="border-b border-coffee bg-deepdark px-4 py-4 space-y-4">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <div className="rounded border border-coffee bg-concrete/50 px-3 py-2">
          <div className="text-2xs text-taupe">Win Rate</div>
          <div className="font-mono text-sm text-cream">
            {summary.winRate.toFixed(1)}%
          </div>
        </div>
        <div className="rounded border border-coffee bg-concrete/50 px-3 py-2">
          <div className="text-2xs text-taupe">Total P&L</div>
          <div
            className={`font-mono text-sm ${
              summary.totalPnl >= 0 ? "text-safe" : "text-error"
            }`}
          >
            {formatCurrency(summary.totalPnl)}
          </div>
        </div>
        <div className="rounded border border-coffee bg-concrete/50 px-3 py-2">
          <div className="text-2xs text-taupe">ROI</div>
          <div
            className={`font-mono text-sm ${
              summary.roi >= 0 ? "text-safe" : "text-error"
            }`}
          >
            {formatPercent(summary.roi)}
          </div>
        </div>
        <div className="rounded border border-coffee bg-concrete/50 px-3 py-2">
          <div className="text-2xs text-taupe">Settled Bets</div>
          <div className="font-mono text-sm text-cream">{summary.settled}</div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded border border-coffee bg-concrete/50 p-3">
          <h3 className="mb-2 text-2xs tracking-wide text-taupe">
            Cumulative P&L
          </h3>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={cumulativePnlData}>
                <CartesianGrid stroke="var(--color-coffee)" strokeDasharray="3 3" />
                <XAxis dataKey="label" stroke="var(--color-stone)" />
                <YAxis stroke="var(--color-stone)" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--color-deepdark)",
                    border: "1px solid var(--color-coffee)",
                    color: "var(--color-cream)",
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="pnl"
                  stroke={CHART_COLORS.pnl}
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded border border-coffee bg-concrete/50 p-3">
          <h3 className="mb-2 text-2xs tracking-wide text-taupe">
            Result Distribution
          </h3>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={outcomeData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={72}
                >
                  {outcomeData.map((entry) => (
                    <Cell key={entry.name} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--color-deepdark)",
                    border: "1px solid var(--color-coffee)",
                    color: "var(--color-cream)",
                  }}
                />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="rounded border border-coffee bg-concrete/50 p-3">
        <h3 className="mb-2 text-2xs tracking-wide text-taupe">
          P&L by League
        </h3>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={leaguePnlData}>
              <CartesianGrid stroke="var(--color-coffee)" strokeDasharray="3 3" />
              <XAxis dataKey="league" stroke="var(--color-stone)" />
              <YAxis stroke="var(--color-stone)" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--color-deepdark)",
                  border: "1px solid var(--color-coffee)",
                  color: "var(--color-cream)",
                }}
              />
              <Bar dataKey="pnl">
                {leaguePnlData.map((entry) => (
                  <Cell
                    key={entry.league}
                    fill={entry.pnl >= 0 ? CHART_COLORS.won : CHART_COLORS.lost}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  );
};
