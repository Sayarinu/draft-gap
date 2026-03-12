"use client";

import { useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
} from "@tanstack/react-table";
import type { PandaScoreUpcomingMatch } from "@/app/types/pandascore";

const columnHelper = createColumnHelper<PandaScoreUpcomingMatch>();

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

function getTeamNames(match: PandaScoreUpcomingMatch): [string, string] {
  const a = match.opponents[0]?.opponent?.name ?? "TBD";
  const b = match.opponents[1]?.opponent?.name ?? "TBD";
  return [a, b];
}

function getTeamAcronyms(match: PandaScoreUpcomingMatch): [string, string] {
  const a = match.opponents[0]?.opponent?.acronym ?? "";
  const b = match.opponents[1]?.opponent?.acronym ?? "";
  return [a, b];
}

function formatMatchType(match: PandaScoreUpcomingMatch): string {
  if (match.match_type === "best_of" && match.number_of_games) {
    return `Bo${match.number_of_games}`;
  }
  return match.match_type ?? "—";
}

interface UpcomingMatchesTableProps {
  matches: PandaScoreUpcomingMatch[];
}

export const UpcomingMatchesTable = ({ matches }: UpcomingMatchesTableProps) => {
  const columns = useMemo(
    () => [
      columnHelper.accessor("scheduled_at", {
        header: "DATE & TIME",
        cell: ({ getValue }) => {
          const { date, time } = formatDateTime(getValue());
          return (
            <div className="space-y-0.5 text-xs">
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
          <div className="text-xs uppercase tracking-wide text-taupe">
            {row.original.league?.name ?? "—"}
          </div>
        ),
      }),
      columnHelper.accessor((m) => m.tournament?.name ?? "", {
        id: "tournament",
        header: "TOURNAMENT",
        cell: ({ row }) => (
          <div className="text-xs text-cream">
            {row.original.tournament?.name ?? "—"}
          </div>
        ),
      }),
      columnHelper.display({
        id: "team1",
        header: "TEAM 1",
        cell: ({ row }) => {
          const [team1] = getTeamNames(row.original);
          const [acr1] = getTeamAcronyms(row.original);
          return (
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-cream">{team1}</span>
              {acr1 && (
                <span className="text-2xs text-taupe font-mono">({acr1})</span>
              )}
            </div>
          );
        },
      }),
      columnHelper.display({
        id: "vs",
        header: "",
        cell: () => (
          <div className="text-xs font-bold text-coffee px-2">VS</div>
        ),
      }),
      columnHelper.display({
        id: "team2",
        header: "TEAM 2",
        cell: ({ row }) => {
          const [, team2] = getTeamNames(row.original);
          const [, acr2] = getTeamAcronyms(row.original);
          return (
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-cream">{team2}</span>
              {acr2 && (
                <span className="text-2xs text-taupe font-mono">({acr2})</span>
              )}
            </div>
          );
        },
      }),
      columnHelper.display({
        id: "format",
        header: "FORMAT",
        cell: ({ row }) => (
          <div className="font-mono text-xs text-cream">
            {formatMatchType(row.original)}
          </div>
        ),
      }),
      columnHelper.accessor((m) => m.streams_list?.[0]?.raw_url ?? null, {
        id: "stream",
        header: "STREAM",
        cell: ({ row }) => {
          const stream = row.original.streams_list?.[0];
          if (!stream?.raw_url) return <span className="text-taupe text-xs">—</span>;
          return (
            <a
              href={stream.raw_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-gold hover:underline"
            >
              Watch
            </a>
          );
        },
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: matches,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="w-full overflow-x-auto bg-deepdark">
      <table className="w-full border-collapse">
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id} className="border-b border-coffee">
              {group.headers.map((header) => (
                <th
                  key={header.id}
                  className="px-4 py-3 text-left text-2xs font-bold uppercase tracking-widest text-cream"
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
                <td key={cell.id} className="px-4 py-3">
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
