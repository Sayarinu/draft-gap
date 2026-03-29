"use client";

import { Fragment, useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
} from "@tanstack/react-table";
import type { LiveMatchWithOdds } from "@/app/types/pandascore";
import type { ActiveSeriesPositionGroup, MatchBettingStatus } from "@/app/types/Betting";
import {
  formatDecimalOdds,
  getTeamName,
} from "@/app/lib/odds";
import { ODDS_TABLE_COLUMN_WIDTHS, RIGHT_OF_VS_COL_IDS } from "./oddsTableConfig";
import { BetDetailsPanel, BetSummaryButton } from "../UI/BetPositionStack";
import { LiveStreamPanel } from "../UI/LiveStreamPanel";

const columnHelper = createColumnHelper<LiveMatchWithOdds>();

interface OddsTrendProps {
  current: number | null;
  priorOdds: number | null;
}

const OddsTrend = ({ current, priorOdds }: OddsTrendProps) => {
  if (current == null) return <span className="text-taupe">—</span>;

  let trendClass = "text-gold";
  let arrow = "";
  if (priorOdds != null && priorOdds > 0) {
    if (current < priorOdds - 0.05) {
      trendClass = "text-safe";
      arrow = " ↓";
    } else if (current > priorOdds + 0.05) {
      trendClass = "text-error";
      arrow = " ↑";
    }
  }

  return (
    <span className={`font-mono text-base font-semibold ${trendClass}`}>
      {current.toFixed(2)}{arrow}
    </span>
  );
};

interface LiveMatchTableProps {
  matches: LiveMatchWithOdds[];
  activeSeriesByMatchId?: Record<number, ActiveSeriesPositionGroup>;
  matchBettingStatusByMatchId?: Record<number, MatchBettingStatus>;
  expandedMatchId: number | null;
  onToggleStream: (match: LiveMatchWithOdds) => void;
}

export const LiveMatchTable = ({
  matches,
  activeSeriesByMatchId = {},
  matchBettingStatusByMatchId = {},
  expandedMatchId,
  onToggleStream,
}: LiveMatchTableProps) => {
  const [expandedBetMatchIds, setExpandedBetMatchIds] = useState<Record<number, boolean>>({});

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: "status",
        header: "DATE & TIME",
        cell: () => (
          <span className="text-[11px] font-semibold uppercase tracking-[0.22em] text-gold">
            Live
          </span>
        ),
      }),
      columnHelper.accessor((m) => m.league_name, {
        id: "league",
        header: "LEAGUE",
        cell: ({ row }) => (
          <div className="text-[11px] uppercase tracking-[0.18em] text-taupe">
            {(row.original.league_name || "—").toUpperCase()}
          </div>
        ),
      }),
      columnHelper.display({
        id: "team1",
        header: "TEAM 1",
        cell: ({ row }) => {
          const team1 = getTeamName(row.original, 1).toUpperCase();
          return (
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold tracking-wide text-white">{team1}</span>
              </div>
            </div>
          );
        },
      }),
      columnHelper.accessor((m) => m.model_odds_team1, {
        id: "model_odds_team1",
        header: "MODEL ODDS",
        cell: ({ row }) => (
          <OddsTrend
            current={row.original.model_odds_team1}
            priorOdds={row.original.pre_match_odds_team1}
          />
        ),
      }),
      columnHelper.accessor((m) => m.bookie_odds_team1, {
        id: "bookie_odds_team1",
        header: "BOOKIE ODDS",
        cell: ({ getValue }) => {
          return (
            <div className="font-mono text-base text-cream">
              {formatDecimalOdds(getValue())}
            </div>
          );
        },
      }),
      columnHelper.display({
        id: "vs",
        header: () => null,
        cell: ({ row }) => {
          const s1 = row.original.series_score_team1 ?? 0;
          const s2 = row.original.series_score_team2 ?? 0;
          const fmt = row.original.series_format;
          const activeSeries = activeSeriesByMatchId[row.original.id];
          if (fmt === "BO1") {
            return (
              <div className="flex w-full flex-col items-center justify-center gap-1 text-center">
                <div className="text-[11px] font-bold uppercase tracking-[0.28em] text-gold">VS</div>
                {activeSeries && (
                  <BetSummaryButton
                    series={activeSeries}
                    expanded={Boolean(expandedBetMatchIds[row.original.id])}
                    onToggle={() =>
                      setExpandedBetMatchIds((current) => ({
                        ...current,
                        [row.original.id]: !current[row.original.id],
                      }))
                    }
                    compact
                  />
                )}
              </div>
            );
          }
          return (
            <div className="flex w-full flex-col items-center justify-center gap-1 text-center">
              <div className="flex items-center justify-center gap-1.5">
                <span className={`font-mono text-sm font-bold ${s1 > s2 ? "text-safe" : "text-cream"}`}>
                  {s1}
                </span>
                <span className="text-xs text-stone">-</span>
                <span className={`font-mono text-sm font-bold ${s2 > s1 ? "text-safe" : "text-cream"}`}>
                  {s2}
                </span>
              </div>
              {activeSeries && (
                <BetSummaryButton
                  series={activeSeries}
                  expanded={Boolean(expandedBetMatchIds[row.original.id])}
                  onToggle={() =>
                    setExpandedBetMatchIds((current) => ({
                      ...current,
                      [row.original.id]: !current[row.original.id],
                    }))
                  }
                  compact
                />
              )}
            </div>
          );
        },
      }),
      columnHelper.accessor((m) => m.bookie_odds_team2, {
        id: "bookie_odds_team2",
        header: "BOOKIE ODDS",
        cell: ({ getValue }) => {
          return (
            <div className="font-mono text-base text-cream">
              {formatDecimalOdds(getValue())}
            </div>
          );
        },
      }),
      columnHelper.accessor((m) => m.model_odds_team2, {
        id: "model_odds_team2",
        header: "MODEL ODDS",
        cell: ({ row }) => (
          <OddsTrend
            current={row.original.model_odds_team2}
            priorOdds={row.original.pre_match_odds_team2}
          />
        ),
      }),
      columnHelper.display({
        id: "team2",
        header: "TEAM 2",
        cell: ({ row }) => {
          const team2 = getTeamName(row.original, 2).toUpperCase();
          return (
            <div className="space-y-1">
              <div className="flex items-center justify-end gap-2">
                <span className="text-sm font-semibold tracking-wide text-white">{team2}</span>
              </div>
            </div>
          );
        },
      }),
      columnHelper.display({
        id: "format",
        header: "FORMAT",
        cell: ({ row }) => (
          <span className="text-2xs font-semibold uppercase tracking-[0.18em] text-taupe">
            {row.original.series_format}
          </span>
        ),
      }),
      columnHelper.accessor((m) => m.stream_url, {
        id: "stream",
        header: "STREAM",
        cell: ({ row }) => {
          const streamUrl = row.original.stream_url;
          if (!streamUrl)
            return <span className="text-stone text-2xs uppercase tracking-[0.18em]">—</span>;
          const isExpanded = expandedMatchId === row.original.id;
          return (
            <button
              type="button"
              onClick={() => onToggleStream(row.original)}
              aria-expanded={isExpanded}
              aria-controls={`live-stream-panel-${row.original.id}`}
              className="text-2xs font-semibold uppercase tracking-[0.18em] text-gold/80 transition-colors hover:text-gold hover:underline"
            >
              {isExpanded ? "Hide" : "Watch"}
            </button>
          );
        },
      }),
    ],
    [activeSeriesByMatchId, expandedBetMatchIds, expandedMatchId, onToggleStream],
  );

  const table = useReactTable({
    data: matches,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="w-full overflow-x-auto bg-deepdark">
      <table
        className="w-full border-collapse table-fixed"
        style={{ minWidth: 800 }}
      >
        <colgroup>
          {ODDS_TABLE_COLUMN_WIDTHS.map((w, i) => (
            <col key={i} style={{ width: w }} />
          ))}
        </colgroup>
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id} className="border-b border-coffee">
              {group.headers.map((header, i) => (
                <th
                  key={header.id}
                  className={`px-3 py-2.5 text-2xs font-semibold uppercase tracking-[0.22em] text-stone ${
                    header.column.id === "vs"
                      ? "text-center"
                      : RIGHT_OF_VS_COL_IDS.has(header.column.id)
                        ? "text-right"
                        : "text-left"
                  }`}
                  style={{ width: ODDS_TABLE_COLUMN_WIDTHS[i] }}
                >
                  {!header.isPlaceholder &&
                    flexRender(
                      header.column.columnDef.header,
                      header.getContext(),
                    )}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody className="divide-y divide-concrete">
          {table.getRowModel().rows.map((row) => {
            const isExpanded = expandedMatchId === row.original.id && Boolean(row.original.stream_url);
            const activeSeries = activeSeriesByMatchId[row.original.id];
            const isBetExpanded = Boolean(activeSeries && expandedBetMatchIds[row.original.id]);
            const matchLabel = `${getTeamName(row.original, 1)} vs ${getTeamName(row.original, 2)}`;

            return (
              <Fragment key={row.original.id}>
                <tr className="transition-colors bg-deepdark hover:bg-concrete/50">
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className={`px-3 py-3.5 align-middle ${
                        cell.column.id === "vs"
                          ? "text-center"
                          : RIGHT_OF_VS_COL_IDS.has(cell.column.id)
                            ? "text-right"
                            : ""
                      }`}
                    >
                      {cell.column.id === "vs" ? (
                        <div className="flex w-full justify-center">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </div>
                      ) : (
                        flexRender(cell.column.columnDef.cell, cell.getContext())
                      )}
                    </td>
                  ))}
                </tr>
                {isBetExpanded && activeSeries ? (
                  <tr className="bg-deepdark/70">
                    <td colSpan={columns.length} className="px-4 pb-4 pt-0">
                      <BetDetailsPanel series={activeSeries} />
                    </td>
                  </tr>
                ) : null}
                {isExpanded && row.original.stream_url ? (
                  <tr id={`live-stream-panel-${row.original.id}`} className="bg-deepdark">
                    <td colSpan={columns.length} className="px-4 pb-4 pt-0">
                      <LiveStreamPanel
                        key={row.original.stream_url}
                        matchLabel={matchLabel}
                        streamUrl={row.original.stream_url}
                      />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
