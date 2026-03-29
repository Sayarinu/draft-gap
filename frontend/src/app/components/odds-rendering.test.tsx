import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { LiveMatchTable } from "./Table/LiveMatchTable";
import { UpcomingWithOddsTable } from "./Table/UpcomingWithOddsTable";
import { LiveMatchCard } from "./UI/LiveMatchCard/LiveMatchCard";
import { LiveStreamPanel } from "./UI/LiveStreamPanel";
import { UpcomingMatchCard } from "./UI/UpcomingMatchCard/UpcomingMatchCard";
import type { ActiveBet, ActiveSeriesPositionGroup, MatchBettingStatus } from "../types/Betting";
import type { LiveMatchWithOdds, UpcomingMatchWithOdds } from "../types/pandascore";

const baseUpcomingMatch: UpcomingMatchWithOdds = {
  id: 1001,
  scheduled_at: "2026-03-22T18:00:00Z",
  league_name: "LCK",
  team1_name: "Alpha",
  team1_acronym: "ALP",
  team2_name: "Beta",
  team2_acronym: "BET",
  stream_url: null,
  bookie_odds_team1: 2.2,
  bookie_odds_team2: 1.7,
  model_odds_team1: 1.9,
  model_odds_team2: 2.05,
  series_format: "BO3",
  markets: [],
};

const baseLiveMatch: LiveMatchWithOdds = {
  ...baseUpcomingMatch,
  stream_url: "https://player.example.com/alpha-beta",
  series_score_team1: 1,
  series_score_team2: 0,
  pre_match_odds_team1: 2.1,
  pre_match_odds_team2: 1.8,
};

const anotherLiveMatch: LiveMatchWithOdds = {
  ...baseLiveMatch,
  id: 1002,
  team1_name: "Delta",
  team1_acronym: "DLT",
  team2_name: "Echo",
  team2_acronym: "ECH",
  stream_url: "https://player.example.com/delta-echo",
};

const team2ActiveBet: ActiveBet = {
  id: "bet-1",
  pandascore_match_id: 1001,
  series_key: "ps:1001",
  bet_sequence: 1,
  bet_on: "Beta",
  market_type: "match_winner",
  source_market_name: "Match Winner",
  source_selection_name: "Beta",
  locked_odds: 1.7,
  stake: 25,
  entry_phase: "live_mid_series",
  entry_score_team_a: 1,
  entry_score_team_b: 0,
  current_score_team_a: 1,
  current_score_team_b: 0,
  feed_health_status: "tracked",
};

const team2Series: ActiveSeriesPositionGroup = {
  series_key: "ps:1001",
  pandascore_match_id: 1001,
  team_a: "Alpha",
  team_b: "Beta",
  league: "LCK",
  position_count: 1,
  total_exposure: 25,
  team_stake_totals: { Alpha: 0, Beta: 25 },
  net_side: "Beta",
  net_stake_delta: 25,
  has_conflicting_positions: false,
  single_position_summary: {
    label: "Bet: Beta @ 1.70",
    side: "Beta",
    locked_odds: 1.7,
    stake: 25,
  },
  multi_position_summary: {
    label: "1 bet",
    bet_count: 1,
    team_a_stake: 0,
    team_b_stake: 25,
    team_a_label: "Alpha",
    team_b_label: "Beta",
    net_side: "Beta",
    net_stake_delta: 25,
  },
  latest_position: team2ActiveBet,
  positions: [team2ActiveBet],
};

const multiBetSeries: ActiveSeriesPositionGroup = {
  ...team2Series,
  position_count: 2,
  total_exposure: 50,
  team_stake_totals: { Alpha: 25, Beta: 25 },
  net_side: null,
  net_stake_delta: 0,
  has_conflicting_positions: true,
  multi_position_summary: {
    label: "2 bets",
    bet_count: 2,
    team_a_stake: 25,
    team_b_stake: 25,
    team_a_label: "Alpha",
    team_b_label: "Beta",
    net_side: null,
    net_stake_delta: 0,
  },
  positions: [
    team2ActiveBet,
    {
      ...team2ActiveBet,
      id: "bet-2",
      bet_sequence: 2,
      bet_on: "Alpha",
      locked_odds: 2.2,
      stake: 25,
      entry_score_team_a: 0,
      entry_score_team_b: 0,
    },
  ],
};

const waitingStatus: MatchBettingStatus = {
  pandascore_match_id: 1001,
  status: "waiting_for_better_odds",
  short_detail: "EDGE 2.0% < 3.0%",
};

const blockedStatus: MatchBettingStatus = {
  pandascore_match_id: 1001,
  status: "blocked_missing_odds",
  reason_code: "missing_bookie_odds",
  short_detail: "NO THUNDERPICK MATCH",
  within_force_window: true,
};

const pendingAutoBetStatus: MatchBettingStatus = {
  pandascore_match_id: 1001,
  status: "pending_auto_bet",
  reason_code: "eligible_auto_bet",
};

const pendingForceBetStatus: MatchBettingStatus = {
  pandascore_match_id: 1001,
  status: "pending_force_bet",
  reason_code: "eligible_force_bet",
  within_force_window: true,
};

describe("odds rendering consistency", () => {
  const ControlledLiveMatchTable = ({ matches }: { matches: LiveMatchWithOdds[] }) => {
    const [expandedMatchId, setExpandedMatchId] = useState<number | null>(null);

    return (
      <LiveMatchTable
        matches={matches}
        expandedMatchId={expandedMatchId}
        onToggleStream={(match) => {
          setExpandedMatchId((current) => (current === match.id ? null : match.id));
        }}
      />
    );
  };

  it("renders upcoming odds in both table and mobile card views", () => {
    render(<UpcomingWithOddsTable matches={[baseUpcomingMatch]} />);

    expect(screen.getAllByText("1.90").length).toBeGreaterThan(0);
    expect(screen.getAllByText("2.20").length).toBeGreaterThan(0);

    render(<UpcomingMatchCard match={baseUpcomingMatch} />);

    expect(screen.getAllByText("1.90").length).toBeGreaterThan(1);
    expect(screen.getAllByText(/2\.20 \/ 1\.70/).length).toBeGreaterThan(0);
  });

  it("renders live odds in both table and mobile card views", () => {
    render(
      <LiveMatchTable
        matches={[baseLiveMatch]}
        expandedMatchId={null}
        onToggleStream={() => undefined}
      />,
    );

    expect(screen.getByText(/1\.90/)).toBeInTheDocument();
    expect(screen.getByText("2.20")).toBeInTheDocument();

    render(<LiveMatchCard match={baseLiveMatch} />);

    expect(screen.getByText("1.90")).toBeInTheDocument();
    expect(screen.getAllByText(/2\.20 \/ 1\.70/).length).toBeGreaterThan(0);
  });

  it("renders team 2 bet details as match-level status in upcoming and live views", () => {
    render(
      <>
        <UpcomingWithOddsTable
          matches={[baseUpcomingMatch]}
          activeSeriesByMatchId={{ 1001: team2Series }}
        />
        <UpcomingMatchCard match={baseUpcomingMatch} activeSeries={team2Series} />
        <LiveMatchTable
          matches={[baseLiveMatch]}
          activeSeriesByMatchId={{ 1001: team2Series }}
          expandedMatchId={null}
          onToggleStream={() => undefined}
        />
        <LiveMatchCard match={baseLiveMatch} activeSeries={team2Series} />
      </>,
    );

    expect(screen.getAllByRole("button", { name: /bet placed/i }).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Bet:/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /bet placed/i })[0]);
    expect(screen.getAllByText(/\$25\.00/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/match win · beta @ 1\.70/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/no bets/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/exposed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^now /i)).not.toBeInTheDocument();
  });

  it("renders a watch button that expands the live stream panel inline", () => {
    render(<ControlledLiveMatchTable matches={[baseLiveMatch]} />);

    fireEvent.click(screen.getByRole("button", { name: /watch/i }));

    expect(screen.getByTitle(/alpha vs beta stream/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open in new tab/i })).toHaveAttribute(
      "href",
      baseLiveMatch.stream_url,
    );

    fireEvent.click(screen.getByRole("button", { name: /hide/i }));

    expect(screen.queryByTitle(/alpha vs beta stream/i)).not.toBeInTheDocument();
  });

  it("allows only one expanded live stream row at a time", () => {
    render(<ControlledLiveMatchTable matches={[baseLiveMatch, anotherLiveMatch]} />);

    fireEvent.click(screen.getAllByRole("button", { name: /watch/i })[0]);
    expect(screen.getByTitle(/alpha vs beta stream/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^watch$/i }));

    expect(screen.queryByTitle(/alpha vs beta stream/i)).not.toBeInTheDocument();
    expect(screen.getByTitle(/delta vs echo stream/i)).toBeInTheDocument();
  });

  it("shows the inline fallback state when the iframe never resolves beyond about:blank", async () => {
    const originalContentWindow = Object.getOwnPropertyDescriptor(
      HTMLIFrameElement.prototype,
      "contentWindow",
    );

    Object.defineProperty(HTMLIFrameElement.prototype, "contentWindow", {
      configurable: true,
      get: () => ({
        location: { href: "about:blank" },
      }),
    });

    vi.useFakeTimers();

    try {
      render(
        <LiveStreamPanel
          matchLabel="Alpha vs Beta"
          streamUrl="https://player.example.com/alpha-beta"
        />,
      );

      await act(async () => {
        await vi.advanceTimersByTimeAsync(8000);
      });

      expect(screen.getByText(/could not be embedded in the app/i)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /open in new tab/i })).toHaveAttribute(
        "href",
        "https://player.example.com/alpha-beta",
      );
    } finally {
      vi.useRealTimers();
      if (originalContentWindow) {
        Object.defineProperty(HTMLIFrameElement.prototype, "contentWindow", originalContentWindow);
      }
    }
  });

  it("renders grouped multi-bet summaries without exposed wording", () => {
    render(
      <>
        <UpcomingWithOddsTable
          matches={[baseUpcomingMatch]}
          activeSeriesByMatchId={{ 1001: multiBetSeries }}
        />
        <LiveMatchCard match={baseLiveMatch} activeSeries={multiBetSeries} />
      </>,
    );

    expect(screen.getAllByRole("button", { name: /bets placed/i }).length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByRole("button", { name: /bets placed/i })[0]);
    expect(screen.getAllByText("ALPHA").length).toBeGreaterThan(0);
    expect(screen.getAllByText("BETA").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$25.00").length).toBeGreaterThan(1);
    expect(screen.queryByText(/exposed/i)).not.toBeInTheDocument();
  });

  it("does not render waiting status copy in upcoming table or card without a placed bet", () => {
    render(
      <>
        <UpcomingWithOddsTable
          matches={[baseUpcomingMatch]}
          matchBettingStatusByMatchId={{ 1001: waitingStatus }}
        />
        <UpcomingMatchCard match={baseUpcomingMatch} matchBettingStatus={waitingStatus} />
      </>,
    );

    expect(screen.queryByText(/waiting · better price/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/edge 2\.0% < 3\.0%/i)).not.toBeInTheDocument();
  });

  it("does not render blocked status copy for upcoming matches when betting is blocked", () => {
    render(
      <>
        <UpcomingWithOddsTable
          matches={[baseUpcomingMatch]}
          matchBettingStatusByMatchId={{ 1001: blockedStatus }}
        />
        <UpcomingMatchCard match={baseUpcomingMatch} matchBettingStatus={blockedStatus} />
      </>,
    );

    expect(screen.queryByText(/blocked · no odds/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/no thunderpick match/i)).not.toBeInTheDocument();
  });

  it("does not render pending auto-bet status for upcoming matches", () => {
    render(
      <>
        <UpcomingWithOddsTable
          matches={[baseUpcomingMatch]}
          matchBettingStatusByMatchId={{ 1001: pendingAutoBetStatus }}
        />
        <UpcomingMatchCard match={baseUpcomingMatch} matchBettingStatus={pendingAutoBetStatus} />
      </>,
    );

    expect(screen.queryByText(/pending · auto bet/i)).not.toBeInTheDocument();
  });

  it("does not render pending force-bet status for upcoming matches", () => {
    render(
      <>
        <UpcomingWithOddsTable
          matches={[baseUpcomingMatch]}
          matchBettingStatusByMatchId={{ 1001: pendingForceBetStatus }}
        />
        <UpcomingMatchCard match={baseUpcomingMatch} matchBettingStatus={pendingForceBetStatus} />
      </>,
    );

    expect(screen.queryByText(/pending · force bet/i)).not.toBeInTheDocument();
  });

  it("does not expose an expandable watch action when a live match has no stream", () => {
    render(
      <LiveMatchTable
        matches={[{ ...baseLiveMatch, id: 3001, stream_url: null }]}
        expandedMatchId={3001}
        onToggleStream={() => undefined}
      />,
    );

    expect(screen.queryByRole("button", { name: /watch/i })).not.toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/live stream/i)).not.toBeInTheDocument();
  });
});
