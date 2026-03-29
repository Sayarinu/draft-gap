"use client";

import { useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
} from "@tanstack/react-table";
import type { UpcomingMatchWithOdds } from "@/app/types/pandascore";

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
  const a = match.team1_name || "TBD";
  const b = match.team2_name || "TBD";
  return [a, b];
}

function formatMatchType(match: UpcomingMatchWithOdds): string {
  return match.series_format ?? "—";
}

interface UpcomingMatchesTableProps {
  matches: UpcomingMatchWithOdds[];
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
      columnHelper.accessor((m) => m.league_name, {
        id: "league",
        header: "LEAGUE",
        cell: ({ row }) => (
          <div className="text-xs uppercase tracking-wide text-taupe">
            {row.original.league_name || "—"}
          </div>
        ),
      }),
      columnHelper.display({
        id: "team1",
        header: "TEAM 1",
        cell: ({ row }) => {
          const [team1] = getTeamNames(row.original);
          return (
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-cream">{team1}</span>
            </div>
          );
        },
      }),
      columnHelper.display({
        id: "vs",
        header: "",
        cell: () => (
          <div className="px-2 text-xs font-bold text-stone">VS</div>
        ),
      }),
      columnHelper.display({
        id: "team2",
        header: "TEAM 2",
        cell: ({ row }) => {
          const [, team2] = getTeamNames(row.original);
          return (
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-cream">{team2}</span>
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
      columnHelper.accessor((m) => m.stream_url, {
        id: "stream",
        header: "STREAM",
        cell: ({ row }) => {
          const streamUrl = row.original.stream_url;
          if (!streamUrl) return <span className="text-taupe text-xs">—</span>;
          return (
            <a
              href={streamUrl}
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
