"use client";

import { useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
} from "@tanstack/react-table";
import { Result } from "@/app/types/Result";
import { MOCK_RESULT_DATA } from "@/app/data/MockResultData";

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

export default function LedgerTable() {
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
          <div className="font-mono text-sm text-soulsilver">
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
          return (
            <div
              className={`text-sm font-bold uppercase tracking-wide ${
                result === "WON" ? "text-safe" : "text-error"
              }`}
            >
              {result}
            </div>
          );
        },
      }),
      columnHelper.accessor("profitLoss", {
        header: "P&L",
        cell: (info) => {
          const val = info.getValue();
          return (
            <div
              className={`font-mono text-sm font-bold tabular-nums ${
                val > 0 ? "text-safe" : val < 0 ? "text-error" : "text-stone"
              }`}
            >
              {val > 0
                ? `+$${val.toFixed(2)}`
                : `-$${Math.abs(val).toFixed(2)}`}
            </div>
          );
        },
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: MOCK_RESULT_DATA,
    columns,

    autoResetPageIndex: false,

    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="w-full overflow-x-auto bg-deepdark">
      <table className="w-full border-collapse">
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id} className="border-b border-coffee">
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-stone"
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
  );
}
