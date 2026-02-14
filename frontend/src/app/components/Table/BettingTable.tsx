"use client";

import { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getGroupedRowModel,
  getExpandedRowModel,
  flexRender,
  createColumnHelper,
  type GroupingState,
  type ExpandedState,
} from "@tanstack/react-table";
import type { Bet } from "@/app/types/Bet";
import { MOCK_BETTING_DATA } from "@/app/data/MockBettingData";

const columnHelper = createColumnHelper<Bet>();

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

export default function BettingTable() {
  const [grouping] = useState<GroupingState>(["matchId"]);
  const [expanded, setExpanded] = useState<ExpandedState>({});

  const columns = useMemo(
    () => [
      columnHelper.accessor("matchId", {
        header: () => null,
        cell: ({ row }) => {
          if (row.getIsGrouped()) {
            const hasMultipleBets = row.subRows.length > 1;
            if (hasMultipleBets) {
              return (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    row.getToggleExpandedHandler()();
                  }}
                  className="text-stone hover:text-cream transition-colors text-sm w-6"
                >
                  {row.getIsExpanded() ? "▼" : "▶"}
                </button>
              );
            }
          }
          return <div className="w-6" />;
        },
      }),
      columnHelper.accessor("gameDateTime", {
        header: "DATE & TIME",
        cell: (info) => {
          if (info.row.getIsGrouped()) {
            const { date, time } = formatDateTime(
              info.row.original.gameDateTime,
            );
            return (
              <div className="space-y-0.5">
                <div className="text-xs text-stone">{date}</div>
                <div className="text-xs text-taupe">{time}</div>
              </div>
            );
          }
          return null;
        },
      }),
      columnHelper.accessor("league", {
        header: "LEAGUE",
        cell: (info) => {
          if (info.row.getIsGrouped()) {
            return (
              <div className="text-xs uppercase tracking-wide text-taupe">
                {info.row.original.league}
              </div>
            );
          }
          return null;
        },
      }),
      columnHelper.accessor("team1", {
        header: "TEAM 1",
        cell: (info) => {
          if (info.row.getIsGrouped()) {
            return (
              <div className="text-sm font-medium text-cream">
                {info.row.original.team1}
              </div>
            );
          }
          return null;
        },
      }),
      columnHelper.accessor("team1ModelOdds", {
        header: "M1",
        cell: (info) => {
          if (info.row.getIsGrouped()) {
            return (
              <div className="font-mono text-sm text-soulsilver">
                {info.row.original.team1ModelOdds.toFixed(2)}
              </div>
            );
          }
          return null;
        },
      }),
      columnHelper.accessor("team1BookieOdds", {
        header: "B1",
        cell: (info) => {
          if (info.row.getIsGrouped()) {
            return (
              <div className="font-mono text-sm text-soulsilver">
                {info.row.original.team1BookieOdds.toFixed(2)}
              </div>
            );
          }
          return null;
        },
      }),
      columnHelper.display({
        id: "vs",
        header: "",
        cell: ({ row }) => {
          if (row.getIsGrouped()) {
            return <div className="text-xs font-bold text-coffee px-2">VS</div>;
          }
          return null;
        },
      }),
      columnHelper.accessor("team2BookieOdds", {
        header: "B2",
        cell: (info) => {
          if (info.row.getIsGrouped()) {
            return (
              <div className="font-mono text-sm text-soulsilver">
                {info.row.original.team2BookieOdds.toFixed(2)}
              </div>
            );
          }
          return null;
        },
      }),
      columnHelper.accessor("team2ModelOdds", {
        header: "M2",
        cell: (info) => {
          if (info.row.getIsGrouped()) {
            return (
              <div className="font-mono text-sm text-soulsilver">
                {info.row.original.team2ModelOdds.toFixed(2)}
              </div>
            );
          }
          return null;
        },
      }),
      columnHelper.accessor("team2", {
        header: "TEAM 2",
        cell: (info) => {
          if (info.row.getIsGrouped()) {
            return (
              <div className="flex items-center gap-2">
                <div className="text-sm font-medium text-cream">
                  {info.row.original.team2}
                </div>
                {info.row.subRows.length > 1 && (
                  <span className="text-[9px] bg-coffee px-2 py-0.5 rounded text-gold font-bold">
                    {info.row.subRows.length} BETS
                  </span>
                )}
              </div>
            );
          }
          return null;
        },
      }),
      columnHelper.accessor("betOn", {
        header: "BET ON",
        cell: (info) => {
          if (info.row.getIsGrouped()) {
            // Show for single bet matches
            if (info.row.subRows.length === 1) {
              return (
                <div className="text-sm font-semibold uppercase tracking-wide text-gold">
                  {info.row.original.betOn}
                </div>
              );
            }
            return null;
          }
          // Show for expanded child rows
          return (
            <div className="text-sm font-semibold uppercase tracking-wide text-gold">
              {info.getValue()}
            </div>
          );
        },
      }),
      columnHelper.accessor("lockedOdds", {
        header: "LOCKED ODDS",
        cell: (info) => {
          if (info.row.getIsGrouped()) {
            // Show for single bet matches
            if (info.row.subRows.length === 1) {
              return (
                <div className="font-mono text-sm font-medium text-cream">
                  {info.row.original.lockedOdds.toFixed(2)}
                </div>
              );
            }
            return null;
          }
          // Show for expanded child rows
          return (
            <div className="font-mono text-sm font-medium text-cream">
              {info.getValue().toFixed(2)}
            </div>
          );
        },
      }),
      columnHelper.accessor("stake", {
        header: "STAKE",
        cell: (info) => {
          if (info.row.getIsGrouped()) {
            const totalStake = info.row.subRows.reduce(
              (sum, row) => sum + row.original.stake,
              0,
            );
            // For single bet, show as regular stake
            if (info.row.subRows.length === 1) {
              return (
                <div className="font-mono text-sm text-cream">
                  ${totalStake.toFixed(2)}
                </div>
              );
            }
            // For multiple bets, show as total
            return (
              <div className="font-mono text-sm font-semibold text-gold">
                ${totalStake.toFixed(2)} total
              </div>
            );
          }
          // Show for expanded child rows
          return (
            <div className="font-mono text-sm text-cream">
              ${info.getValue().toFixed(2)}
            </div>
          );
        },
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: MOCK_BETTING_DATA,
    columns,
    state: {
      grouping,
      expanded,
    },
    onExpandedChange: setExpanded,

    autoResetPageIndex: false,
    autoResetExpanded: false,

    getCoreRowModel: getCoreRowModel(),
    getGroupedRowModel: getGroupedRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
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
          {table.getRowModel().rows.map((row) => {
            const isGrouped = row.getIsGrouped();
            const hasMultipleBets = isGrouped && row.subRows.length > 1;

            return (
              <tr
                key={row.id}
                className={`transition-colors bg-deepdark hover:bg-concrete/50 ${
                  isGrouped && hasMultipleBets ? "cursor-pointer" : ""
                }`}
                onClick={
                  hasMultipleBets ? row.getToggleExpandedHandler() : undefined
                }
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-4 py-3">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
