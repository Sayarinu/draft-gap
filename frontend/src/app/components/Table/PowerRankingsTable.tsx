"use client";

import { useEffect, useMemo, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { fetchPowerRankings } from "@/app/lib/api";
import { useIsMobile } from "@/app/lib/useMediaQuery";
import type { PowerRankingRow } from "@/app/types/PowerRanking";
import { PowerRankingCard } from "@/app/components/UI/PowerRankingCard/PowerRankingCard";

const columnHelper = createColumnHelper<PowerRankingRow>();

const POWER_RANKING_COLUMN_WIDTHS = [
  "6%",
  "21%",
  "10%",
  "8%",
  "9%",
  "10%",
  "9%",
  "9%",
  "9%",
  "7%",
  "12%",
] as const;

const LEAGUE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "all", label: "ALL REGIONS" },
  { value: "lck", label: "LCK" },
  { value: "lpl", label: "LPL" },
  { value: "lec", label: "LEC" },
  { value: "lcs", label: "LCS" },
  { value: "cblol", label: "CBLOL" },
  { value: "lcp", label: "LCP" },
];

function sortIndicator(sorted: false | "asc" | "desc"): string {
  if (sorted === "asc") return " ▲";
  if (sorted === "desc") return " ▼";
  return "";
}

function formatPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function winRateColor(value: number): string {
  if (value >= 0.65) return "text-safe";
  if (value >= 0.5) return "text-gold";
  return "text-error";
}

const LOADING_COPY = "Loading power rankings…";

export const PowerRankingsTable = () => {
  const isMobile = useIsMobile();
  const [rows, setRows] = useState<PowerRankingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [league, setLeague] = useState("all");
  const [sorting, setSorting] = useState<SortingState>([{ id: "rank", desc: false }]);

  useEffect(() => {
    let cancelled = false;
    const run = () => {
      fetchPowerRankings(league)
        .then((data) => {
          if (!cancelled) {
            setRows(data);
            setError(null);
          }
        })
        .catch((e) => {
          if (!cancelled) {
            setRows([]);
            setError(e instanceof Error ? e.message : "Failed to load rankings");
          }
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };
    setLoading(true);
    run();
    const id = setInterval(run, 300_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [league]);

  const columns = useMemo(
    () => [
      columnHelper.accessor("rank", {
        header: "RANK",
        cell: (info) => (
          <span className="font-mono text-sm font-bold text-gold">#{info.getValue()}</span>
        ),
      }),
      columnHelper.display({
        id: "team",
        header: "TEAM",
        enableSorting: true,
        sortingFn: (a, b) => a.original.team.localeCompare(b.original.team),
        cell: ({ row }) => <div className="text-sm font-medium text-cream">{row.original.team}</div>,
      }),
      columnHelper.accessor("league_slug", {
        header: "LEAGUE",
        cell: ({ row }) => (
          <span className="text-xs font-semibold uppercase tracking-wide text-cream">
            {row.original.league_slug}
          </span>
        ),
      }),
      columnHelper.display({
        id: "record",
        header: "RECORD",
        enableSorting: true,
        sortingFn: (a, b) => a.original.wins - b.original.wins,
        cell: ({ row }) => (
          <span className="font-mono text-sm text-cream">
            {row.original.wins}-{row.original.losses}
          </span>
        ),
      }),
      columnHelper.accessor("win_rate", {
        header: "WIN RATE",
        cell: (info) => (
          <span className={`font-mono text-sm font-semibold ${winRateColor(info.getValue())}`}>
            {formatPct(info.getValue())}
          </span>
        ),
      }),
      columnHelper.accessor("avg_game_duration_min", {
        header: "AVG MINS",
        cell: (info) => (
          <span className="font-mono text-sm text-cream">{info.getValue().toFixed(1)}</span>
        ),
      }),
      columnHelper.accessor("avg_gold_diff_15", {
        header: "GD@15",
        cell: (info) => {
          const value = info.getValue();
          const rounded = Number(value.toFixed(0));
          if (rounded === 0) {
            return <span className="font-mono text-sm text-taupe">-</span>;
          }
          const color = value >= 0 ? "text-safe" : "text-error";
          const sign = value > 0 ? "+" : "";
          return (
            <span className={`font-mono text-sm font-semibold ${color}`}>
              {sign}
              {rounded}
            </span>
          );
        },
      }),
      columnHelper.accessor("first_blood_pct", {
        header: "FB%",
        cell: (info) => (
          <span className="font-mono text-sm text-cream">{formatPct(info.getValue())}</span>
        ),
      }),
      columnHelper.accessor("first_dragon_pct", {
        header: "DRG%",
        cell: (info) => (
          <span className="font-mono text-sm text-cream">{formatPct(info.getValue())}</span>
        ),
      }),
      columnHelper.accessor("first_tower_pct", {
        header: "TWR%",
        cell: (info) => (
          <span className="font-mono text-sm text-cream">{formatPct(info.getValue())}</span>
        ),
      }),
      columnHelper.accessor("games_played", {
        header: "GAMES",
        cell: (info) => (
          <span className="font-mono text-sm text-taupe">{info.getValue()}</span>
        ),
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (loading) {
    return <div className="p-8 text-center text-taupe">{LOADING_COPY}</div>;
  }

  if (error) {
    return <div className="p-8 text-center text-error">{error}</div>;
  }

  if (rows.length === 0) {
    return <div className="p-8 text-center text-taupe">NO ACTIVE TEAMS FOUND FOR THIS FILTER.</div>;
  }

  const sortedRows = table.getRowModel().rows.map((r) => r.original);

  return (
    <div className="w-full bg-deepdark">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-coffee px-3 py-3 sm:px-4">
        <div className="text-2xs font-semibold uppercase tracking-widest text-taupe sm:text-xs">
          TEAM POWER RANKINGS (LAST 90 DAYS)
        </div>
        <label className="flex items-center gap-2 text-2xs uppercase tracking-wide text-taupe sm:text-xs">
          Region
          <select
            value={league}
            onChange={(event) => setLeague(event.target.value)}
            className="rounded border border-coffee bg-deepdark px-2 py-1 text-2xs text-cream focus:outline-none focus:ring-1 focus:ring-gold sm:text-xs"
          >
            {LEAGUE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {isMobile ? (
        <div className="divide-y divide-concrete">
          {sortedRows.map((row) => (
            <PowerRankingCard key={`${row.league_slug}-${row.team}-${row.rank}`} row={row} />
          ))}
        </div>
      ) : (
        <div className="w-full overflow-x-auto">
          <table className="w-full table-fixed border-collapse" style={{ minWidth: 1100 }}>
            <colgroup>
              {POWER_RANKING_COLUMN_WIDTHS.map((width, idx) => (
                <col key={idx} style={{ width }} />
              ))}
            </colgroup>
            <thead>
              {table.getHeaderGroups().map((group) => (
                <tr key={group.id} className="border-b border-coffee">
                  {group.headers.map((header, idx) => {
                    const sorted = header.column.getIsSorted();
                    return (
                      <th
                        key={header.id}
                        onClick={header.column.getToggleSortingHandler()}
                        style={{ width: POWER_RANKING_COLUMN_WIDTHS[idx] }}
                        className="cursor-pointer select-none px-4 py-3 text-left text-2xs font-bold uppercase tracking-widest text-cream hover:text-gold"
                      >
                        {header.isPlaceholder ? null : (
                          <span>
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {sortIndicator(sorted)}
                          </span>
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody className="divide-y divide-concrete">
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="transition-colors hover:bg-concrete">
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-3">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
