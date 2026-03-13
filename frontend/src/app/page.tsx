"use client";

import { useEffect, useMemo, useState } from "react";
import {
  fetchActiveBets,
  fetchBettingResults,
  fetchLiveWithOdds,
  fetchOddsRefreshGlobalStatus,
  fetchUpcomingWithOdds,
} from "@/app/lib/api";
import {
  formatLastRefreshAgo,
  formatRefreshCountdown,
  formatRefreshStageLabel,
  parseIsoDate,
} from "@/app/lib/formatting";
import {
  getLeagueName,
  getResultLeagueName,
  isTbdVsTbd,
  matchesResultSearch,
  matchesSearch,
} from "@/app/lib/matchFilters";
import { Header } from "./components/Header";
import { LiveMatchTable } from "./components/Table/LiveMatchTable";
import { PowerRankingsTable } from "./components/Table/PowerRankingsTable";
import { ResultTable } from "./components/Table/ResultTable";
import { UpcomingWithOddsTable } from "./components/Table/UpcomingWithOddsTable";
import { BankrollSummaryBar } from "./components/UI/BankrollSummaryBar/BankrollSummaryBar";
import { ResultsMetrics } from "./components/UI/ResultsMetrics/ResultsMetrics";
import { SearchFilterRefreshBar } from "./components/UI/SearchFilterRefreshBar/SearchFilterRefreshBar";
import { TabEnum } from "./enums/tabs";
import type { LiveMatchWithOdds, UpcomingMatchWithOdds } from "./types/pandascore";
import type { ActiveBet } from "./types/Betting";
import type { Result } from "./types/Result";

export const Home = () => {
  const [tab, setTab] = useState<TabEnum>(TabEnum.Upcoming);
  const [matches, setMatches] = useState<UpcomingMatchWithOdds[]>([]);
  const [liveMatches, setLiveMatches] = useState<LiveMatchWithOdds[]>([]);
  const [loading, setLoading] = useState(true);
  const [liveLoading, setLiveLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [activeBetsByMatchId, setActiveBetsByMatchId] = useState<Record<number, ActiveBet>>({});
  const [selectedEvents, setSelectedEvents] = useState<Set<string>>(new Set());
  const [filterPanelOpen, setFilterPanelOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [isUpcomingRefreshing, setIsUpcomingRefreshing] = useState(false);
  const [results, setResults] = useState<Result[]>([]);
  const [resultsLoading, setResultsLoading] = useState(false);
  const [resultsError, setResultsError] = useState<string | null>(null);
  const [resultSelectedEvents, setResultSelectedEvents] = useState<Set<string>>(new Set());
  const [resultFilterPanelOpen, setResultFilterPanelOpen] = useState(false);
  const [resultSearchQuery, setResultSearchQuery] = useState("");
  const [isResultsRefreshing, setIsResultsRefreshing] = useState(false);
  const [bankrollRefreshKey, setBankrollRefreshKey] = useState(0);
  const [lastRefreshAt, setLastRefreshAt] = useState<Date | null>(null);
  const [nextRefreshAt, setNextRefreshAt] = useState<Date | null>(null);
  const [refreshClockMs, setRefreshClockMs] = useState<number>(() => Date.now());
  const [upcomingRefreshProgress, setUpcomingRefreshProgress] = useState(0);
  const [upcomingRefreshStage, setUpcomingRefreshStage] = useState("");

  const eventOptions = useMemo(() => {
    const leagues = new Set<string>();
    liveMatches.forEach((m) => {
      const name = getLeagueName(m);
      if (name) leagues.add(name);
    });
    matches.forEach((m) => {
      const name = getLeagueName(m);
      if (name) leagues.add(name);
    });
    return Array.from(leagues).sort((a, b) => a.localeCompare(b));
  }, [liveMatches, matches]);

  const filteredLive = useMemo(() => {
    const byEvent =
      selectedEvents.size === 0
        ? liveMatches
        : liveMatches.filter((m) => selectedEvents.has(getLeagueName(m)));
    return byEvent.filter(
      (m) =>
        !isTbdVsTbd(m) &&
        getLeagueName(m).toUpperCase() !== "VCS" &&
        matchesSearch(m, searchQuery),
    );
  }, [liveMatches, selectedEvents, searchQuery]);

  const filteredUpcoming = useMemo(() => {
    const byEvent =
      selectedEvents.size === 0
        ? matches
        : matches.filter((m) => selectedEvents.has(getLeagueName(m)));
    return byEvent.filter((m) => !isTbdVsTbd(m) && matchesSearch(m, searchQuery));
  }, [matches, selectedEvents, searchQuery]);

  const resultEventOptions = useMemo(() => {
    const leagues = new Set<string>();
    results.forEach((r) => {
      const name = getResultLeagueName(r);
      if (name) leagues.add(name);
    });
    return Array.from(leagues).sort((a, b) => a.localeCompare(b));
  }, [results]);

  const filteredResults = useMemo(() => {
    const byEvent =
      resultSelectedEvents.size === 0
        ? results
        : results.filter((r) => resultSelectedEvents.has(getResultLeagueName(r)));
    return byEvent.filter((r) => matchesResultSearch(r, resultSearchQuery));
  }, [resultSearchQuery, resultSelectedEvents, results]);

  const orphanedBets = useMemo(() => {
    const matchIdsInTable = new Set([
      ...matches.map((m) => m.id),
      ...liveMatches.map((m) => m.id),
    ]);
    return Object.values(activeBetsByMatchId).filter(
      (bet) => !matchIdsInTable.has(bet.pandascore_match_id),
    );
  }, [activeBetsByMatchId, matches, liveMatches]);

  const handleToggleEvent = (eventName: string) => {
    setSelectedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(eventName)) next.delete(eventName);
      else next.add(eventName);
      return next;
    });
  };

  const handleClearFilter = () => setSelectedEvents(new Set());
  const handleToggleResultEvent = (eventName: string) => {
    setResultSelectedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(eventName)) next.delete(eventName);
      else next.add(eventName);
      return next;
    });
  };
  const handleClearResultFilter = () => setResultSelectedEvents(new Set());

  const UPCOMING_POLL_MS = 900_000;
  const LIVE_POLL_MS = 900_000;
  const ACTIVE_BETS_POLL_MS = 300_000;
  const RESULTS_POLL_MS = 60_000;

  const lastRefreshLabel =
    lastRefreshAt !== null
      ? formatLastRefreshAgo(lastRefreshAt, refreshClockMs)
      : "";
  const nextRefreshLabel =
    nextRefreshAt !== null
      ? formatRefreshCountdown(nextRefreshAt, refreshClockMs)
      : "";

  const runUpcomingFetch = (cancelled: boolean) => {
    fetchUpcomingWithOdds(100)
      .then((data) => {
        if (!cancelled) setMatches(data);
      })
      .catch((e) => {
        if (!cancelled) {
          console.error("[Draft Gap] Upcoming fetch failed:", e);
          setError(e instanceof Error ? e.message : "Failed to load matches");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
  };

  const runActiveBetsFetch = (cancelled: boolean) => {
    fetchActiveBets()
      .then((rows) => {
        if (cancelled) return;
        const next: Record<number, ActiveBet> = {};
        rows.forEach((row) => {
          next[row.pandascore_match_id] = row;
        });
        setActiveBetsByMatchId(next);
      })
      .catch(() => {
        if (!cancelled) setActiveBetsByMatchId({});
      });
  };

  const runLiveFetch = (cancelled: boolean) => {
    fetchLiveWithOdds(20)
      .then((data) => {
        if (!cancelled) setLiveMatches(data);
      })
      .catch((e) => {
        if (!cancelled) {
          console.error("[Draft Gap] Live fetch failed:", e);
          setLiveError(e instanceof Error ? e.message : "Failed to load live matches");
        }
      })
      .finally(() => {
        if (!cancelled) setLiveLoading(false);
      });
  };

  const runResultsFetch = (cancelled: boolean) => {
    if (!cancelled) setResultsLoading(true);
    fetchBettingResults(500)
      .then((data) => {
        if (!cancelled) {
          setResults(data);
          setResultsError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setResultsError(
            e instanceof Error ? e.message : "Failed to load results",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setResultsLoading(false);
      });
  };

  const handleUpcomingRefresh = () => {};

  const handleResultsRefresh = () => {
    setIsResultsRefreshing(true);
    setResultsLoading(true);
    setBankrollRefreshKey((k) => k + 1);
    fetchBettingResults(500)
      .then((data) => {
        setResults(data);
        setResultsError(null);
      })
      .catch((e) => {
        setResultsError(
          e instanceof Error ? e.message : "Failed to load results",
        );
      })
      .finally(() => {
        setResultsLoading(false);
        setIsResultsRefreshing(false);
      });
  };

  useEffect(() => {
    let cancelled = false;
    const run = () => runUpcomingFetch(cancelled);
    run();
    const id = setInterval(run, UPCOMING_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (tab !== TabEnum.Results) return;
    let cancelled = false;
    const run = () => runResultsFetch(cancelled);
    run();
    const id = setInterval(run, RESULTS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [tab]);

  useEffect(() => {
    let cancelled = false;
    const run = () => runActiveBetsFetch(cancelled);
    run();
    const id = setInterval(run, ACTIVE_BETS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [ACTIVE_BETS_POLL_MS]);

  useEffect(() => {
    let cancelled = false;
    const run = () => runLiveFetch(cancelled);
    run();
    const id = setInterval(run, LIVE_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (tab !== TabEnum.Upcoming) return;
    const id = setInterval(() => setRefreshClockMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [tab]);

  useEffect(() => {
    if (tab !== TabEnum.Upcoming) return;
    let cancelled = false;
    const pollMs = isUpcomingRefreshing ? 5_000 : 10_000;
    const run = () => {
      fetchOddsRefreshGlobalStatus()
        .then((status) => {
          if (cancelled) return;
          setIsUpcomingRefreshing(status.in_progress);
          setUpcomingRefreshProgress(status.progress ?? 0);
          setUpcomingRefreshStage(status.stage ?? "");
          setLastRefreshAt(parseIsoDate(status.last_completed_at ?? null));
          setNextRefreshAt(parseIsoDate(status.next_scheduled_at ?? null));
        })
        .catch(() => {
          if (!cancelled) {
            setIsUpcomingRefreshing(false);
            setLastRefreshAt(null);
            setNextRefreshAt(null);
          }
        });
    };
    run();
    const id = setInterval(run, pollMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [tab, isUpcomingRefreshing]);

  return (
    <div className="flex flex-col flex-1 bg-concrete">
      <Header currentTab={tab} setTab={setTab} />

      <div className="flex-1 overflow-y-auto">
        {tab === TabEnum.Upcoming && (
          <>
            <BankrollSummaryBar
              refreshKey={bankrollRefreshKey}
              isRefreshing={isUpcomingRefreshing}
            />
            {!loading && !error && (matches.length > 0 || liveMatches.length > 0) && (
              <SearchFilterRefreshBar
                onRefresh={handleUpcomingRefresh}
                isRefreshing={isUpcomingRefreshing}
                refreshProgress={upcomingRefreshProgress}
                refreshStageLabel={upcomingRefreshStage}
                refreshButtonDisabled
                lastRefreshLabel={lastRefreshLabel}
                nextRefreshLabel={nextRefreshLabel}
                filterPanelOpen={filterPanelOpen}
                onToggleFilterPanel={() => setFilterPanelOpen((open) => !open)}
                onCloseFilterPanel={() => setFilterPanelOpen(false)}
                selectedCount={selectedEvents.size}
                searchValue={searchQuery}
                onSearchChange={setSearchQuery}
                searchPlaceholder="SEARCH TEAMS OR EVENTS..."
                searchAriaLabel="Search matches"
                eventOptions={eventOptions}
                selectedEvents={selectedEvents}
                onToggleEvent={handleToggleEvent}
                onClearFilter={handleClearFilter}
              />
            )}
            {loading && (
              <div className="p-8 text-center text-taupe">
                Loading upcoming matches…
              </div>
            )}
            {error && (
              <div className="p-8 text-center text-error">{error}</div>
            )}
            {!loading && !error && matches.length === 0 && liveMatches.length === 0 && (
              <div className="p-8 text-center text-taupe">
                No upcoming matches at the moment.
              </div>
            )}
            {!loading && !error && (matches.length > 0 || liveMatches.length > 0) && (
              <>
                <section className="border-b border-soulsilver/50">
                  <h2 className="px-4 py-2 text-sm font-medium uppercase tracking-wide text-gold bg-deepdark/50">
                    Live now
                  </h2>
                  {liveLoading ? (
                    <div className="p-4 text-center text-taupe text-sm">Loading live…</div>
                  ) : liveError ? (
                    <div className="p-4 text-center text-error text-sm">{liveError}</div>
                  ) : filteredLive.length === 0 ? (
                    <div className="p-6 text-center text-taupe text-sm uppercase tracking-wide bg-deepdark">
                      No live matches
                    </div>
                  ) : (
                    <LiveMatchTable
                      matches={filteredLive as LiveMatchWithOdds[]}
                      activeBetsByMatchId={activeBetsByMatchId}
                    />
                  )}
                </section>
                <section>
                  <h2 className="px-4 py-2 text-sm font-medium uppercase tracking-wide text-cream bg-deepdark/30">
                    Upcoming
                  </h2>
                  {filteredUpcoming.length === 0 ? (
                    <div className="p-6 text-center text-taupe text-sm uppercase tracking-wide bg-deepdark space-y-2">
                      <p>
                        {matches.length === 0
                          ? "No upcoming matches at the moment."
                          : "No upcoming matches for the selected events."}
                      </p>
                      {matches.length > 0 && selectedEvents.size > 0 && (
                        <button
                          type="button"
                          onClick={handleClearFilter}
                          className="text-gold hover:underline text-xs normal-case"
                        >
                          Clear filter to see all
                        </button>
                      )}
                    </div>
                  ) : (
                    <UpcomingWithOddsTable
                      matches={filteredUpcoming}
                      activeBetsByMatchId={activeBetsByMatchId}
                    />
                  )}
                </section>
                {orphanedBets.length > 0 && (
                  <section className="border-t border-soulsilver/50">
                    <h2 className="px-4 py-2 text-sm font-medium uppercase tracking-wide text-taupe bg-deepdark/30">
                      Active bets not in schedule
                    </h2>
                    <p className="px-4 py-1 text-xs text-taupe/70">
                      These matches are no longer in the upcoming or live list. Bets will settle automatically when results are confirmed.
                    </p>
                    <ul className="divide-y divide-soulsilver/30">
                      {orphanedBets.map((bet) => (
                        <li key={bet.id} className="flex items-center gap-3 px-4 py-3 text-sm">
                          <span className="rounded bg-gold/10 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-gold">
                            Bet Placed
                          </span>
                          <span className="font-medium text-cream">{bet.bet_on}</span>
                          <span className="text-taupe">
                            @ <span className="font-mono text-cream">{bet.locked_odds.toFixed(2)}</span>
                          </span>
                          <span className="text-taupe">
                            Stake: <span className="font-mono text-cream">${bet.stake.toFixed(2)}</span>
                          </span>
                          <span className="ml-auto text-xs text-taupe/60 font-mono">
                            Match #{bet.pandascore_match_id}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </>
            )}
          </>
        )}
        {tab === TabEnum.Results && (
          <>
            <BankrollSummaryBar
              refreshKey={bankrollRefreshKey}
              isRefreshing={isResultsRefreshing}
            />
            {!resultsLoading && !resultsError && results.length > 0 && (
              <SearchFilterRefreshBar
                onRefresh={handleResultsRefresh}
                isRefreshing={isResultsRefreshing}
                filterPanelOpen={resultFilterPanelOpen}
                onToggleFilterPanel={() => setResultFilterPanelOpen((open) => !open)}
                onCloseFilterPanel={() => setResultFilterPanelOpen(false)}
                selectedCount={resultSelectedEvents.size}
                searchValue={resultSearchQuery}
                onSearchChange={setResultSearchQuery}
                searchPlaceholder="SEARCH TEAMS OR EVENTS..."
                searchAriaLabel="Search results"
                eventOptions={resultEventOptions}
                selectedEvents={resultSelectedEvents}
                onToggleEvent={handleToggleResultEvent}
                onClearFilter={handleClearResultFilter}
              />
            )}
            {resultsLoading && (
              <div className="p-8 text-center text-taupe">LOADING SETTLED BETS...</div>
            )}
            {resultsError && (
              <div className="p-8 text-center text-error">{resultsError}</div>
            )}
            {!resultsLoading && !resultsError && results.length === 0 && (
              <div className="p-8 text-center text-taupe">NO SETTLED BETS YET</div>
            )}
            {!resultsLoading && !resultsError && results.length > 0 && (
              <>
                <ResultsMetrics results={filteredResults} />
                <ResultTable results={filteredResults} />
              </>
            )}
          </>
        )}
        {tab === TabEnum.PowerRankings && <PowerRankingsTable />}
      </div>
    </div>
  );
};

export default Home;
