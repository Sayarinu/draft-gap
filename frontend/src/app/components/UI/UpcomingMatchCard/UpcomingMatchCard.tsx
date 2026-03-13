"use client";

import type { UpcomingMatchWithOdds } from "@/app/types/pandascore";
import type { ActiveBet } from "@/app/types/Betting";

interface UpcomingMatchCardProps {
  match: UpcomingMatchWithOdds;
  activeBet?: ActiveBet | null;
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

function getEdge(
  match: UpcomingMatchWithOdds,
  team: 1 | 2,
): number | null {
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
}

export const UpcomingMatchCard = ({ match, activeBet }: UpcomingMatchCardProps) => {
  const team1 = match.opponents[0]?.opponent?.name ?? "TBD";
  const team2 = match.opponents[1]?.opponent?.name ?? "TBD";
  const acr1 = (match.opponents[0]?.opponent?.acronym ?? "").toUpperCase();
  const acr2 = (match.opponents[1]?.opponent?.acronym ?? "").toUpperCase();
  const { date, time } = formatDateTime(match.scheduled_at);
  const edge1 = getEdge(match, 1);
  const edge2 = getEdge(match, 2);
  const streamUrl = match.streams_list?.[0]?.raw_url;
  const fmt = match.series_format;

  return (
    <article className="border-b border-concrete bg-deepdark px-4 py-3 last:border-b-0">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-2xs uppercase tracking-wide text-taupe">
          {(match.league?.name ?? "—").toUpperCase()}
        </span>
        <span className="text-2xs text-taupe">
          {date} · {time}
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium text-cream">
              {team1.toUpperCase()}
            </span>
            {acr1 && <span className="text-2xs font-mono text-taupe">({acr1})</span>}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
            {edge1 != null && edge1 > 0.03 ? (
              <span className="rounded bg-safe/20 px-1.5 py-0.5 text-2xs font-bold text-safe">
                +{(edge1 * 100).toFixed(1)}%
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
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="font-mono text-sm text-gold">
            {match.model_odds_team1 != null ? match.model_odds_team1.toFixed(2) : "—"}
          </span>
          <span className="text-xs font-bold text-coffee">VS</span>
          <span className="font-mono text-sm text-gold">
            {match.model_odds_team2 != null ? match.model_odds_team2.toFixed(2) : "—"}
          </span>
        </div>
        <div className="min-w-0 flex-1 text-right">
          <div className="flex items-center justify-end gap-1.5">
            {acr2 && <span className="text-2xs font-mono text-taupe">({acr2})</span>}
            <span className="truncate text-sm font-medium text-cream">
              {team2.toUpperCase()}
            </span>
          </div>
          <div className="mt-0.5 flex flex-wrap justify-end gap-1.5">
            {edge2 != null && edge2 > 0.03 ? (
              <span className="rounded bg-safe/20 px-1.5 py-0.5 text-2xs font-bold text-safe">
                +{(edge2 * 100).toFixed(1)}%
              </span>
            ) : (
              <span className="rounded bg-concrete px-1.5 py-0.5 text-2xs font-bold text-taupe">
                NO EDGE
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-concrete/50 pt-2">
        <div className="flex items-center gap-2">
          <span className="text-2xs text-taupe">Bookie:</span>
          <span className="font-mono text-2xs text-soulsilver">
            {match.bookie_odds_team1 != null ? match.bookie_odds_team1.toFixed(2) : "—"} /{" "}
            {match.bookie_odds_team2 != null ? match.bookie_odds_team2.toFixed(2) : "—"}
          </span>
          {fmt && (
            <span className="rounded bg-concrete px-1.5 py-0.5 text-2xs font-bold uppercase tracking-wider text-cream">
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
      {activeBet && (
        <p className="mt-1 text-2xs text-taupe">
          Agent bet: {activeBet.bet_on.toUpperCase()} @ {activeBet.locked_odds.toFixed(2)} ($
          {activeBet.stake.toFixed(2)})
        </p>
      )}
    </article>
  );
};
