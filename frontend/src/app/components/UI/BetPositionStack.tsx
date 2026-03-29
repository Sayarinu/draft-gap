"use client";

import { useId, useState } from "react";

import type { ActiveBet, ActiveSeriesPositionGroup } from "@/app/types/Betting";

interface BetDetailsCommonProps {
  series?: ActiveSeriesPositionGroup | null;
}

interface BetSummaryButtonProps extends BetDetailsCommonProps {
  expanded: boolean;
  onToggle: () => void;
  compact?: boolean;
}

interface BetDetailsPanelProps extends BetDetailsCommonProps {
  compact?: boolean;
}

interface BetPositionStackProps extends BetDetailsCommonProps {
  compact?: boolean;
  defaultExpanded?: boolean;
}

function formatMoney(value: number | null | undefined): string {
  return `$${(value ?? 0).toFixed(2)}`;
}

function formatPhase(value: string | null | undefined): string {
  return value === "live_mid_series" ? "LIVE" : "PRE";
}

function formatFeedStatus(position: ActiveBet): string {
  const raw = position.feed_health_status ?? position.status ?? "tracked";
  return String(raw).replaceAll("_", " ").toUpperCase();
}

export function formatMarketLabel(position: ActiveBet): string {
  const sourceMarketName = String(position.source_market_name ?? "").trim();
  const sourceSelectionName = String(position.source_selection_name ?? "").trim();
  const marketType = position.market_type ?? "match_winner";
  if (/^map\s+\d+/i.test(sourceMarketName)) {
    return sourceSelectionName
      ? `${sourceMarketName.toUpperCase()} · ${sourceSelectionName.toUpperCase()}`
      : sourceMarketName.toUpperCase();
  }
  if (sourceMarketName.toLowerCase() === "match winner" || marketType === "match_winner") {
    return `MATCH WIN · ${position.bet_on.toUpperCase()}`;
  }
  if (marketType === "map_handicap") {
    const line = position.line_value == null ? "" : ` ${position.line_value > 0 ? "+" : ""}${position.line_value.toFixed(1)}`;
    return `WIN${line} · ${position.bet_on.toUpperCase()}`;
  }
  if (marketType === "total_maps") {
    const line = position.line_value == null ? "" : ` ${position.line_value.toFixed(1)}`;
    const selection = sourceSelectionName || String(position.selection_key ?? position.bet_on).replaceAll("_", " ");
    return `${selection.toUpperCase()}${line} MAPS`;
  }
  if (sourceMarketName && sourceSelectionName) {
    return `${sourceMarketName.toUpperCase()} · ${sourceSelectionName.toUpperCase()}`;
  }
  if (sourceMarketName) return sourceMarketName.toUpperCase();
  return position.bet_on.toUpperCase();
}

function getSummaryText(series: ActiveSeriesPositionGroup): string {
  return series.position_count > 1 ? "BETS PLACED" : "BET PLACED";
}

export const BetSummaryButton = ({
  series,
  expanded,
  onToggle,
  compact = false,
}: BetSummaryButtonProps) => {
  if (!series || series.positions.length === 0) return null;

  const label = getSummaryText(series);
  const count = series.position_count;
  const stakeText = formatMoney(series.total_exposure);
  const detailParts =
    count > 1 ? [`${count} bets`, stakeText] : [stakeText];

  return (
    <button
      type="button"
      onClick={onToggle}
      className={`inline-flex max-w-full flex-wrap items-center gap-x-2 gap-y-0.5 rounded border border-gold/45 bg-gold/[0.08] font-mono text-gold transition-colors hover:bg-gold/[0.12] ${compact ? "px-2 py-1 text-[10px]" : "px-2.5 py-1 text-[11px]"}`}
      aria-expanded={expanded}
      aria-label={`${label}, ${detailParts.join(", ")}`}
    >
      <span className="inline-flex shrink-0 items-center gap-1.5">
        <span className="text-gold/70">{expanded ? "▾" : "▸"}</span>
        <span>{label}</span>
      </span>
      <span className="min-w-0 text-gold/75">
        <span aria-hidden="true">{detailParts.join(" · ")}</span>
      </span>
    </button>
  );
};

export const BetDetailsPanel = ({
  series,
  compact = false,
}: BetDetailsPanelProps) => {
  if (!series || series.positions.length === 0) return null;

  const summary = series.multi_position_summary;
  const groupedPositions = [
    {
      label: summary?.team_a_label ?? series.team_a,
      positions: series.positions.filter((position) => position.bet_on === series.team_a),
    },
    {
      label: summary?.team_b_label ?? series.team_b,
      positions: series.positions.filter((position) => position.bet_on === series.team_b),
    },
  ];

  return (
    <div className={`rounded border border-concrete/60 bg-black/20 p-2 text-left ${compact ? "text-[10px]" : "text-[11px]"}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 font-mono text-gold/80">
        <span>Total stake {formatMoney(series.total_exposure)}</span>
        <span>
          {series.net_side ? `Lean ${String(series.net_side).toUpperCase()}` : "Balanced"}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {groupedPositions.map((group) => (
          <div key={group.label} className="rounded border border-concrete/40 px-2 py-2">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 font-mono text-cream/90">
              <span className="min-w-0 break-words">{String(group.label).toUpperCase()}</span>
              <span className="shrink-0">{formatMoney(series.team_stake_totals[group.label] ?? 0)}</span>
            </div>
            <div className="space-y-1.5">
              {group.positions.length === 0 ? (
                <div className="rounded border border-dashed border-concrete/20 px-2 py-2 font-mono text-cream/35">
                  No bets
                </div>
              ) : null}
              {group.positions.map((position) => {
                return (
                  <div
                    key={position.id ?? `${series.series_key}-${position.bet_sequence}`}
                    className="rounded border border-concrete/30 bg-deepdark/50 px-2 py-1.5 font-mono text-cream/90"
                  >
                    <div className="flex flex-col gap-1 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between sm:gap-x-2 sm:gap-y-0">
                      <span className="min-w-0 break-words leading-snug">
                        {formatMarketLabel(position)} @ {position.locked_odds.toFixed(2)}
                      </span>
                      <span className="shrink-0 sm:text-right">{formatMoney(position.stake)}</span>
                    </div>
                    <div className="mt-1 flex flex-col gap-0.5 text-cream/70 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-2">
                      <span>{formatFeedStatus(position)}</span>
                      <span className="shrink-0">
                        {formatPhase(position.entry_phase)} · Bet {position.bet_sequence ?? "—"}
                      </span>
                    </div>
                    <div className="mt-1 break-words text-cream/55">
                      Entry {position.entry_score_team_a ?? 0}-{position.entry_score_team_b ?? 0} · Current{" "}
                      {position.current_score_team_a ?? 0}-{position.current_score_team_b ?? 0}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export const BetPositionStack = ({
  series,
  compact = false,
  defaultExpanded = false,
}: BetPositionStackProps) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const panelId = useId();

  if (!series || series.positions.length === 0) return null;

  return (
    <div className="space-y-2">
      <BetSummaryButton
        series={series}
        expanded={expanded}
        onToggle={() => setExpanded((current) => !current)}
        compact={compact}
      />
      {expanded ? (
        <div id={panelId}>
          <BetDetailsPanel series={series} compact={compact} />
        </div>
      ) : null}
    </div>
  );
};
