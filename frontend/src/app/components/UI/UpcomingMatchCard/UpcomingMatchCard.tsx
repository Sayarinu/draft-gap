"use client";

import {
  formatDecimalOdds,
  getTeamName,
} from "@/app/lib/odds";
import type { UpcomingMatchWithOdds } from "@/app/types/pandascore";
import type { ActiveSeriesPositionGroup, MatchBettingStatus } from "@/app/types/Betting";
import { BetPositionStack } from "../BetPositionStack";

interface UpcomingMatchCardProps {
  match: UpcomingMatchWithOdds;
  activeSeries?: ActiveSeriesPositionGroup | null;
  matchBettingStatus?: MatchBettingStatus | null;
}

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

export const UpcomingMatchCard = ({ match, activeSeries, matchBettingStatus }: UpcomingMatchCardProps) => {
  const team1 = getTeamName(match, 1);
  const team2 = getTeamName(match, 2);
  const { date, time } = formatDateTime(match.scheduled_at);
  const streamUrl = match.stream_url;
  const fmt = match.series_format;
  void matchBettingStatus;

  return (
    <article className="border-b border-concrete bg-deepdark px-4 py-3 last:border-b-0">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-2xs uppercase tracking-wide text-taupe">
          {(match.league_name || "—").toUpperCase()}
        </span>
        <span className="text-2xs text-taupe">
          {date} · {time}
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium text-white">
              {team1.toUpperCase()}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="font-mono text-sm text-gold">{formatDecimalOdds(match.model_odds_team1)}</span>
          <span className="text-xs font-bold text-gold">VS</span>
          <span className="font-mono text-sm text-gold">{formatDecimalOdds(match.model_odds_team2)}</span>
        </div>
        <div className="min-w-0 flex-1 text-right">
          <div className="flex items-center justify-end gap-1.5">
            <span className="truncate text-sm font-medium text-white">
              {team2.toUpperCase()}
            </span>
          </div>
        </div>
      </div>
      {activeSeries && (
        <div className="mt-2 border-t border-concrete/50 pt-2 text-left">
          <BetPositionStack series={activeSeries} defaultExpanded={false} compact />
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-concrete/50 pt-2">
        <div className="flex items-center gap-2">
          <span className="text-2xs text-taupe">Bookie:</span>
          <span className="font-mono text-2xs text-cream">
            {formatDecimalOdds(match.bookie_odds_team1)} / {formatDecimalOdds(match.bookie_odds_team2)}
          </span>
          {fmt && (
            <span className="text-2xs font-semibold uppercase tracking-[0.18em] text-taupe">
              {fmt}
            </span>
          )}
        </div>
        {streamUrl ? (
          <a
            href={streamUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-medium uppercase tracking-wide text-gold hover:underline"
          >
            Watch
          </a>
        ) : (
          <span className="text-2xs uppercase text-taupe">—</span>
        )}
      </div>
    </article>
  );
};
