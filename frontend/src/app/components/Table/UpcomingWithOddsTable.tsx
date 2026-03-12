"use client";

import { useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
} from "@tanstack/react-table";
import type { UpcomingMatchWithOdds } from "@/app/types/pandascore";
import type { ActiveBet } from "@/app/types/Betting";

export const RIGHT_OF_VS_COL_IDS = new Set([
  "bookie_odds_team2",
  "model_odds_team2",
  "team2",
  "format",
  "stream",
]);

export const ODDS_TABLE_COLUMN_WIDTHS = [
  "10%",
  "8%",
  "14%",
  "7.5%",
  "7.5%",
  "6%",
  "7.5%",
  "7.5%",
  "14%",
  "6%",
  "12%",
] as const;

const columnHelper = createColumnHelper<UpcomingMatchWithOdds>();

function formatDateTime(isoString: string) {
  const date = new Date(isoString);
  return {
    date: date.toLocaleDateString(undefined, {
      month: "numeric",
      day: "numeric",
      year: "numeric",
    }),
    time: date.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    }),
  };
}

function getTeamNames(match: UpcomingMatchWithOdds): [string, string] {
  const a = match.opponents[0]?.opponent?.name ?? "TBD";
  const b = match.opponents[1]?.opponent?.name ?? "TBD";
  return [a.toUpperCase(), b.toUpperCase()];
}

function getTeamAcronyms(match: UpcomingMatchWithOdds): [string, string] {
  const a = match.opponents[0]?.opponent?.acronym ?? "";
  const b = match.opponents[1]?.opponent?.acronym ?? "";
  return [a.toUpperCase(), b.toUpperCase()];
}

interface UpcomingWithOddsTableProps {
  matches: UpcomingMatchWithOdds[];
  activeBetsByMatchId?: Record<number, ActiveBet>;
}

export const UpcomingWithOddsTable = ({
  matches,
  activeBetsByMatchId = {},
}: UpcomingWithOddsTableProps) => {
  const getEdge = (match: UpcomingMatchWithOdds, team: 1 | 2): number | null => {
    const model = team === 1 ? match.model_odds_team1 : match.model_odds_team2;
    const bookA = match.bookie_odds_team1;
    const bookB = match.bookie_odds_team2;
    if (model == null || bookA == null || bookB == null || model <= 0 || bookA <= 0 || bookB <= 0) {
      return null;
    }
    const impliedA = 1 / bookA;
    const impliedB = 1 / bookB;
    const denom = impliedA + impliedB;
    if (denom <= 0) return null;
    const bookAdj = team === 1 ? impliedA / denom : impliedB / denom;
    const modelProb = 1 / model;
    return modelProb - bookAdj;
  };

  const columns = useMemo(
    () => [
      columnHelper.accessor("scheduled_at", {
        header: "DATE & TIME",
        cell: ({ getValue }) => {
          const { date, time } = formatDateTime(getValue());
          return (
            <div className="space-y-0.5 text-xs uppercase">
              <div className="text-cream">{date}</div>
              <div className="text-taupe">{time}</div>
            </div>
          );
        },
      }),
      columnHelper.accessor((m) => m.league?.name ?? "", {
        id: "league",
        header: "LEAGUE",
        cell: ({ row }) => (
          <div className="text-xs uppercase tracking-wide text-cream">
            {(row.original.league?.name ?? "—").toUpperCase()}
          </div>
        ),
      }),
      columnHelper.display({
        id: "team1",
        header: "TEAM 1",
        cell: ({ row }) => {
          const [team1] = getTeamNames(row.original);
          const [acr1] = getTeamAcronyms(row.original);
          const edge = getEdge(row.original, 1);
          const activeBet = activeBetsByMatchId[row.original.id];
          return (
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-cream">{team1}</span>
                {acr1 && (
                  <span className="text-2xs text-taupe font-mono">({acr1})</span>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                {edge != null && edge > 0.03 ? (
                  <span className="rounded bg-safe/20 px-1.5 py-0.5 text-2xs font-bold text-safe">
                    +{(edge * 100).toFixed(1)}%
                  </span>
                ) : (
                  <span className="rounded bg-concrete px-1.5 py-0.5 text-2xs font-bold text-taupe">
                    NO EDGE
                  </span>
                )}
                {activeBet && (
                  <span className="rounded bg-gold/20 px-1.5 py-0.5 text-2xs font-bold text-gold">
                    BET PLACED
                  </span>
                )}
              </div>
              {activeBet && (
                <div className="text-2xs text-taupe">
                  Agent bet: {activeBet.bet_on.toUpperCase()} @ {activeBet.locked_odds.toFixed(2)} (${activeBet.stake.toFixed(2)})
                </div>
              )}
            </div>
          );
        },
      }),
      columnHelper.accessor((m) => m.model_odds_team1, {
        id: "model_odds_team1",
        header: "MODEL ODDS",
        cell: ({ getValue }) => {
          const v = getValue();
          return (
            <div className="font-mono text-sm text-gold">
              {v != null ? v.toFixed(2) : "—"}
            </div>
          );
        },
      }),
      columnHelper.accessor((m) => m.bookie_odds_team1, {
        id: "bookie_odds_team1",
        header: "BOOKIE ODDS",
        cell: ({ getValue }) => {
          const v = getValue();
          return (
            <div className="font-mono text-sm text-soulsilver">
              {v != null ? v.toFixed(2) : "—"}
            </div>
          );
        },
      }),
      columnHelper.display({
        id: "vs",
        header: () => null,
        cell: () => (
          <div className="text-xs font-bold text-coffee">VS</div>
        ),
      }),
      columnHelper.accessor((m) => m.bookie_odds_team2, {
        id: "bookie_odds_team2",
        header: "BOOKIE ODDS",
        cell: ({ getValue }) => {
          const v = getValue();
          return (
            <div className="font-mono text-sm text-soulsilver">
              {v != null ? v.toFixed(2) : "—"}
            </div>
          );
        },
      }),
      columnHelper.accessor((m) => m.model_odds_team2, {
        id: "model_odds_team2",
        header: "MODEL ODDS",
        cell: ({ getValue }) => {
          const v = getValue();
          return (
            <div className="font-mono text-sm text-gold">
              {v != null ? v.toFixed(2) : "—"}
            </div>
          );
        },
      }),
      columnHelper.display({
        id: "team2",
        header: "TEAM 2",
        cell: ({ row }) => {
          const [, team2] = getTeamNames(row.original);
          const [, acr2] = getTeamAcronyms(row.original);
          const edge = getEdge(row.original, 2);
          return (
            <div className="space-y-1">
              <div className="flex items-center justify-end gap-2">
                {acr2 && (
                  <span className="text-2xs text-taupe font-mono">({acr2})</span>
                )}
                <span className="text-sm font-medium text-cream">{team2}</span>
              </div>
              <div className="flex items-center justify-end gap-1.5">
                {edge != null && edge > 0.03 ? (
                  <span className="rounded bg-safe/20 px-1.5 py-0.5 text-2xs font-bold text-safe">
                    +{(edge * 100).toFixed(1)}%
                  </span>
                ) : (
                  <span className="rounded bg-concrete px-1.5 py-0.5 text-2xs font-bold text-taupe">
                    NO EDGE
                  </span>
                )}
              </div>
            </div>
          );
        },
      }),
      columnHelper.display({
        id: "format",
        header: "FORMAT",
        cell: ({ row }) => {
          const fmt = (row.original as UpcomingMatchWithOdds).series_format;
          if (!fmt) return null;
          return (
            <span className="inline-block rounded bg-concrete px-1.5 py-0.5 text-2xs font-bold uppercase tracking-wider text-cream">
              {fmt}
            </span>
          );
        },
      }),
      columnHelper.accessor((m) => m.streams_list?.[0]?.raw_url ?? null, {
        id: "stream",
        header: "STREAM",
        cell: ({ row }) => {
          const stream = row.original.streams_list?.[0];
          if (!stream?.raw_url)
            return <span className="text-taupe text-xs uppercase">—</span>;
          return (
            <a
              href={stream.raw_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-gold hover:underline uppercase"
            >
              Watch
            </a>
          );
        },
      }),
    ],
    [activeBetsByMatchId],
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
                  className={`px-4 py-3 text-2xs font-bold uppercase tracking-widest text-cream ${
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
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.original.id}
              className="transition-colors bg-deepdark hover:bg-concrete/50"
            >
              {row.getVisibleCells().map((cell) => (
                <td
                  key={cell.id}
                  className={`px-4 py-3 ${
                    cell.column.id === "vs"
                      ? "text-center"
                      : RIGHT_OF_VS_COL_IDS.has(cell.column.id)
                        ? "text-right"
                        : ""
                  }`}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
