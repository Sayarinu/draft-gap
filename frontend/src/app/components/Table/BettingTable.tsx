"use client";

import { useState, useMemo, ReactNode } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getGroupedRowModel,
  getExpandedRowModel,
  flexRender,
  createColumnHelper,
  type GroupingState,
  type ExpandedState,
  Row,
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

const GroupOnly = ({
  row,
  children,
}: {
  row: Row<Bet>;
  children: ReactNode;
}) => (row.getIsGrouped() ? <>{children}</> : null);

export const BettingTable = () => {
  const [grouping] = useState<GroupingState>(["matchId"]);
  const [expanded, setExpanded] = useState<ExpandedState>({});

  const columns = useMemo(
    () => [
      columnHelper.accessor("matchId", {
        header: () => null,
        cell: ({ row }) => (
          <div className="w-6">
            {row.getIsGrouped() && row.subRows.length > 1 && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  row.getToggleExpandedHandler()();
                }}
                className="text-stone hover:text-cream transition-colors text-sm"
              >
                {row.getIsExpanded() ? "▼" : "▶"}
              </button>
            )}
          </div>
        ),
      }),
      columnHelper.accessor("gameDateTime", {
        header: "DATE & TIME",
        cell: ({ row }) => {
          const { date, time } = formatDateTime(row.original.gameDateTime);
          return (
            <GroupOnly row={row}>
              <div className="space-y-0.5 text-xs">
                <div className="text-stone">{date}</div>
                <div className="text-taupe">{time}</div>
              </div>
            </GroupOnly>
          );
        },
      }),
      columnHelper.accessor("league", {
        header: "LEAGUE",
        cell: ({ row }) => (
          <GroupOnly row={row}>
            <div className="text-xs uppercase tracking-wide text-taupe">
              {row.original.league}
            </div>
          </GroupOnly>
        ),
      }),
      columnHelper.accessor("team1", {
        header: "TEAM 1",
        cell: ({ row }) => (
          <GroupOnly row={row}>
            <div className="text-sm font-medium text-cream">
              {row.original.team1}
            </div>
          </GroupOnly>
        ),
      }),
      columnHelper.accessor("team1ModelOdds", {
        header: "M1",
        cell: ({ row }) => (
          <GroupOnly row={row}>
            <div className="font-mono text-sm text-soulsilver">
              {row.original.team1ModelOdds.toFixed(2)}
            </div>
          </GroupOnly>
        ),
      }),
      columnHelper.accessor("team1BookieOdds", {
        header: "B1",
        cell: ({ row }) => (
          <GroupOnly row={row}>
            <div className="font-mono text-sm text-soulsilver">
              {row.original.team1BookieOdds.toFixed(2)}
            </div>
          </GroupOnly>
        ),
      }),
      columnHelper.display({
        id: "vs",
        cell: ({ row }) => (
          <GroupOnly row={row}>
            <div className="text-xs font-bold text-coffee px-2">VS</div>
          </GroupOnly>
        ),
      }),
      columnHelper.accessor("team2BookieOdds", {
        header: "B2",
        cell: ({ row }) => (
          <GroupOnly row={row}>
            <div className="font-mono text-sm text-soulsilver">
              {row.original.team2BookieOdds.toFixed(2)}
            </div>
          </GroupOnly>
        ),
      }),
      columnHelper.accessor("team2ModelOdds", {
        header: "M2",
        cell: ({ row }) => (
          <GroupOnly row={row}>
            <div className="font-mono text-sm text-soulsilver">
              {row.original.team2ModelOdds.toFixed(2)}
            </div>
          </GroupOnly>
        ),
      }),
      columnHelper.accessor("team2", {
        header: "TEAM 2",
        cell: ({ row }) => (
          <GroupOnly row={row}>
            <div className="flex items-center gap-2">
              <div className="text-sm font-medium text-cream">
                {row.original.team2}
              </div>
              {row.subRows.length > 1 && (
                <span className="text-[9px] bg-coffee px-2 py-0.5 rounded text-gold font-bold">
                  {row.subRows.length} BETS
                </span>
              )}
            </div>
          </GroupOnly>
        ),
      }),
      columnHelper.accessor("betOn", {
        header: "BET ON",
        cell: ({ row, getValue }) => {
          if (!row.getIsGrouped()) {
            return (
              <div className="text-sm font-semibold uppercase tracking-wide text-gold">
                {getValue()}
              </div>
            );
          }
          if (row.subRows.length === 1) {
            return (
              <div className="text-sm font-semibold uppercase tracking-wide text-gold">
                {row.subRows[0].original.betOn}
              </div>
            );
          }
          return null;
        },
      }),
      columnHelper.accessor("lockedOdds", {
        header: "LOCKED ODDS",
        cell: ({ row, getValue }) => {
          if (!row.getIsGrouped()) {
            return (
              <div className="font-mono text-sm font-medium text-cream">
                {getValue().toFixed(2)}
              </div>
            );
          }
          if (row.subRows.length === 1) {
            return (
              <div className="font-mono text-sm font-medium text-cream">
                {row.subRows[0].original.lockedOdds.toFixed(2)}
              </div>
            );
          }
          return null;
        },
      }),
      columnHelper.accessor("stake", {
        header: "STAKE",
        cell: ({ row, getValue }) => {
          const totalStake = row.getIsGrouped()
            ? row.subRows.reduce((sum, r) => sum + r.original.stake, 0)
            : getValue();
          const isMultiBetGroup = row.getIsGrouped() && row.subRows.length > 1;
          return (
            <div
              className={`font-mono text-sm ${isMultiBetGroup ? "font-semibold text-gold" : "text-cream"}`}
            >
              ${totalStake.toFixed(2)}
              {isMultiBetGroup && " total"}
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
    state: { grouping, expanded },
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
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id} className="border-b border-coffee">
              {group.headers.map((header) => (
                <th
                  key={header.id}
                  className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-stone"
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
            const hasMultiple = row.getIsGrouped() && row.subRows.length > 1;
            return (
              <tr
                key={row.id}
                className={`transition-colors bg-deepdark hover:bg-concrete/50 ${hasMultiple ? "cursor-pointer" : ""}`}
                onClick={
                  hasMultiple ? row.getToggleExpandedHandler() : undefined
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
};

export default BettingTable;
