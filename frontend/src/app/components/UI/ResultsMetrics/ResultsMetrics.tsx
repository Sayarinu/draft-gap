"use client";

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

import type { ResultsAnalytics } from "@/app/types/Result";
import { useIsMobile } from "@/app/lib/useMediaQuery";

interface ResultsMetricsProps {
  analytics: ResultsAnalytics;
}

interface ChartTooltipProps {
  active?: boolean;
  label?: string;
  payload?: Array<{
    color?: string;
    dataKey?: string;
    name?: string;
    value?: number | string;
    payload?: {
      league?: string;
      name?: string;
      profit?: number;
      value?: number;
    };
  }>;
  variant: "cumulative" | "distribution" | "league";
  settledBets: number;
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
  profit: "var(--color-gold)",
};

const ResultsChartTooltip = ({
  active,
  label,
  payload,
  variant,
  settledBets,
}: ChartTooltipProps) => {
  if (!active || !payload?.length) return null;

  const primary = payload[0];
  const numericValue =
    typeof primary?.value === "number"
      ? primary.value
      : Number(primary?.value ?? 0);

  let eyebrow = "";
  let title = label ?? primary?.name ?? primary?.payload?.name ?? primary?.payload?.league ?? "";
  let detail = "";

  if (variant === "cumulative") {
    eyebrow = "Running Profit";
    detail = `${formatCurrency(numericValue)} after settled bets through ${title}`;
  } else if (variant === "distribution") {
    const count = primary?.payload?.value ?? numericValue;
    const share = settledBets > 0 ? (count / settledBets) * 100 : 0;
    eyebrow = "Outcome Split";
    title = primary?.payload?.name ?? title;
    detail = `${count} bets, ${share.toFixed(1)}% of settled volume`;
  } else {
    const direction = numericValue >= 0 ? "Net gain" : "Net loss";
    eyebrow = "Event Performance";
    title = primary?.payload?.league ?? title;
    detail = `${direction} of ${formatCurrency(numericValue)} across settled results`;
  }

  return (
    <div className="min-w-44 rounded border border-coffee bg-deepdark/95 px-3 py-2 shadow-[0_0_0_1px_rgba(4,4,4,0.4)]">
      <div className="text-3xs tracking-[0.22em] text-stone">{eyebrow}</div>
      <div className="mt-1 text-xs text-cream">{title}</div>
      <div className="mt-2 font-mono text-sm text-cream">{detail}</div>
    </div>
  );
};

export const ResultsMetrics = ({ analytics }: ResultsMetricsProps) => {
  const isMobile = useIsMobile();
  const summary = analytics.summary;
  const outcomeData = analytics.outcome_data.map((entry) => ({
    ...entry,
    color: entry.name === "Won" ? CHART_COLORS.won : CHART_COLORS.lost,
  }));
  const cumulativeProfitData = analytics.cumulative_profit_data;
  const leagueProfitData = analytics.league_profit_data;
  const hasLeagueProfitData = leagueProfitData.length > 0;

  if (summary.settled === 0) return null;

  return (
    <section className="flex min-h-full flex-col border-b border-coffee bg-deepdark px-4 py-4">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <div className="rounded border border-coffee bg-concrete/50 px-3 py-2">
          <div className="text-2xs text-taupe">Win Rate</div>
          <div className="font-mono text-sm text-cream">
            {summary.win_rate.toFixed(1)}%
          </div>
        </div>
        <div className="rounded border border-coffee bg-concrete/50 px-3 py-2">
          <div className="text-2xs text-taupe">Total Profit</div>
          <div
            className={`font-mono text-sm ${
              summary.total_profit >= 0 ? "text-safe" : "text-error"
            }`}
          >
            {formatCurrency(summary.total_profit)}
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

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="min-w-0 rounded border border-coffee bg-concrete/50 p-3">
          <h3 className="mb-2 text-2xs tracking-wide text-taupe">
            Cumulative Profit
          </h3>
          <div className={isMobile ? "h-48" : "h-60"}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={cumulativeProfitData}>
                <CartesianGrid stroke="var(--color-coffee)" strokeDasharray="3 3" />
                <XAxis dataKey="label" stroke="var(--color-stone)" hide={isMobile} />
                <YAxis stroke="var(--color-stone)" hide={isMobile} />
                <Tooltip
                  cursor={{ stroke: "var(--color-coffee)", strokeDasharray: "4 4" }}
                  content={
                    <ResultsChartTooltip
                      variant="cumulative"
                      settledBets={summary.settled}
                    />
                  }
                />
                <Line
                  type="monotone"
                  dataKey="profit"
                  stroke={CHART_COLORS.profit}
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="min-w-0 rounded border border-coffee bg-concrete/50 p-3">
          <h3 className="mb-2 text-2xs tracking-wide text-taupe">
            Result Distribution
          </h3>
          <div className={isMobile ? "h-44" : "h-52"}>
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
                  content={
                    <ResultsChartTooltip
                      variant="distribution"
                      settledBets={summary.settled}
                    />
                  }
                />
                {!isMobile && <Legend />}
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {!isMobile && (
        <div className="mt-4 min-w-0 flex-1 rounded border border-coffee bg-concrete/50 p-3">
          <h3 className="mb-2 text-2xs tracking-wide text-taupe">
            Profit by Event
          </h3>
          <div className="h-80 min-h-[20rem] xl:h-[26rem]">
            {hasLeagueProfitData ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={leagueProfitData}>
                  <CartesianGrid stroke="var(--color-coffee)" strokeDasharray="3 3" />
                  <XAxis dataKey="league" stroke="var(--color-stone)" />
                  <YAxis stroke="var(--color-stone)" />
                  <Tooltip
                    cursor={false}
                    content={
                      <ResultsChartTooltip
                        variant="league"
                        settledBets={summary.settled}
                      />
                    }
                  />
                  <Bar
                    dataKey="profit"
                    activeBar={{
                      fillOpacity: 1,
                      stroke: "var(--color-cream)",
                      strokeWidth: 1,
                    }}
                  >
                    {leagueProfitData.map((entry) => (
                      <Cell
                        key={entry.league}
                        fill={entry.profit >= 0 ? CHART_COLORS.won : CHART_COLORS.lost}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center border border-dashed border-coffee/60 bg-deepdark/35 text-xs uppercase tracking-[0.2em] text-taupe">
                No settled event profit yet
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
};
