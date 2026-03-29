"use client";

import { useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
} from "@tanstack/react-table";
import { Result } from "@/app/types/Result";

const columnHelper = createColumnHelper<Result>();

const formatDateTime = (isoString: string) => {
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
};

const formatCurrency = (val: number) => {
  const sign = val > 0 ? "+" : val < 0 ? "-" : "";
  return `${sign}$${Math.abs(val).toFixed(2)}`;
};

interface ResultTableProps {
  results: Result[];
}

const ResultCard = ({ result }: { result: Result }) => {
  const { date, time } = formatDateTime(result.betDateTime);
  const profitColor =
    result.profit > 0 ? "text-safe" : result.profit < 0 ? "text-error" : "text-stone";
  const resultColor =
    result.result === "WON"
      ? "text-safe"
      : result.result === "LOST"
        ? "text-error"
        : "text-taupe";

  return (
    <article className="space-y-3 border-b border-concrete bg-deepdark px-4 py-4 last:border-b-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-2xs font-semibold uppercase tracking-wide text-taupe">
            {result.league}
          </div>
          <div className="mt-1 text-sm font-medium text-cream">
            {result.team1} vs {result.team2}
          </div>
          <div className="mt-1 text-2xs text-stone">
            {date} · {time}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className={`text-xs font-bold uppercase tracking-wide ${resultColor}`}>
            {result.result}
          </div>
          <div className={`mt-1 font-mono text-sm font-bold ${profitColor}`}>
            {formatCurrency(result.profit)}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 border-t border-concrete/50 pt-3">
        <div>
          <div className="text-2xs uppercase tracking-wide text-taupe">Bet On</div>
          <div className="mt-1 text-sm font-semibold uppercase tracking-wide text-gold">
            {result.betOn}
          </div>
        </div>
        <div>
          <div className="text-2xs uppercase tracking-wide text-taupe">Odds</div>
          <div className="mt-1 font-mono text-sm text-cream">
            {result.lockedOdds.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="text-2xs uppercase tracking-wide text-taupe">Stake</div>
          <div className="mt-1 font-mono text-sm text-cream">
            ${result.stake.toFixed(2)}
          </div>
        </div>
      </div>
    </article>
  );
};

export const ResultTable = ({ results }: ResultTableProps) => {
  const columns = useMemo(
    () => [
      columnHelper.accessor("betDateTime", {
        header: "BET PLACED",
        cell: (info) => {
          const { date, time } = formatDateTime(info.getValue());
          return (
            <div className="space-y-0.5">
              <div className="text-xs text-stone">{date}</div>
              <div className="text-xs text-taupe">{time}</div>
            </div>
          );
        },
      }),
      columnHelper.accessor("league", {
        header: "LEAGUE",
        cell: (info) => (
          <div className="text-xs uppercase tracking-wide text-taupe">
            {info.getValue()}
          </div>
        ),
      }),
      columnHelper.display({
        id: "matchup",
        header: "MATCHUP",
        cell: ({ row }) => (
          <div className="text-sm font-medium text-cream">
            {row.original.team1} vs {row.original.team2}
          </div>
        ),
      }),
      columnHelper.accessor("betOn", {
        header: "BET ON",
        cell: (info) => (
          <div className="text-sm font-semibold uppercase tracking-wide text-gold">
            {info.getValue()}
          </div>
        ),
      }),
      columnHelper.accessor("lockedOdds", {
        header: "LOCKED ODDS",
        cell: (info) => (
          <div className="font-mono text-sm text-cream">
            {info.getValue().toFixed(2)}
          </div>
        ),
      }),
      columnHelper.accessor("stake", {
        header: "STAKE",
        cell: (info) => (
          <div className="font-mono text-sm text-cream">
            ${info.getValue().toFixed(2)}
          </div>
        ),
      }),
      columnHelper.accessor("result", {
        header: "RESULT",
        cell: (info) => {
          const result = info.getValue();
          const color =
            result === "WON"
              ? "text-safe"
              : result === "LOST"
                ? "text-error"
                : "text-taupe";
          return (
            <div
              className={`text-sm font-bold uppercase tracking-wide ${color}`}
            >
              {result}
            </div>
          );
        },
      }),
      columnHelper.accessor("profit", {
        header: "PROFIT",
        cell: (info) => {
          const val = info.getValue();
          const color =
            val > 0 ? "text-safe" : val < 0 ? "text-error" : "text-stone";
          return (
            <div
              className={`font-mono text-sm font-bold tabular-nums ${color}`}
            >
              {formatCurrency(val)}
            </div>
          );
        },
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: results,
    columns,
    autoResetPageIndex: false,
    getCoreRowModel: getCoreRowModel(),
  });

  if (results.length === 0) {
    return (
      <div className="p-8 text-center text-taupe">
        No settled bets yet.
      </div>
    );
  }

  return (
    <>
      <div className="divide-y divide-concrete bg-deepdark md:hidden">
        {results.map((result) => (
          <ResultCard key={result.id} result={result} />
        ))}
      </div>
      <div className="hidden w-full overflow-x-auto bg-deepdark md:block">
        <table className="w-full border-collapse">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b border-coffee">
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="px-4 py-3 text-left text-2xs font-bold uppercase tracking-widest text-stone"
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(
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
    </>
  );
};
