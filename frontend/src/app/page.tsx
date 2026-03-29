"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchBettingHistory,
  fetchHomepageBootstrap,
  fetchLiveWithOdds,
  fetchResultsAnalytics,
  fetchUpcomingWithOdds,
} from "@/app/lib/api";
import {
  formatLastRefreshAgo,
  parseIsoDate,
} from "@/app/lib/formatting";
import { Header } from "./components/Header";
import { LiveMatchTable } from "./components/Table/LiveMatchTable";
import { PowerRankingsTable } from "./components/Table/PowerRankingsTable";
import { ResultTable } from "./components/Table/ResultTable";
import { UpcomingWithOddsTable } from "./components/Table/UpcomingWithOddsTable";
import { BankrollSummaryBar } from "./components/UI/BankrollSummaryBar/BankrollSummaryBar";
import { LiveMatchCard } from "./components/UI/LiveMatchCard/LiveMatchCard";
import { SearchFilterRefreshBar } from "./components/UI/SearchFilterRefreshBar/SearchFilterRefreshBar";
import { ResultsMetrics } from "./components/UI/ResultsMetrics/ResultsMetrics";
import { UpcomingMatchCard } from "./components/UI/UpcomingMatchCard/UpcomingMatchCard";
import { TabEnum } from "./enums/tabs";
import type { ActiveSeriesPositionGroup, BankrollSummary, MatchBettingStatus } from "./types/Betting";
import type { Result, ResultsAnalytics } from "./types/Result";
import type {
  LiveMatchWithOdds,
  PaginatedMatchesResponse,
  UpcomingMatchWithOdds,
} from "./types/pandascore";

interface SectionFreshnessStatus {
  data_as_of?: string | null;
  generated_at?: string | null;
  is_stale?: boolean;
  status?: string | null;
  source?: string | null;
}

const LIVE_ACTIVE_POLL_MS = 15_000;
const STANDARD_POLL_MS = 60_000;
const BACKGROUND_POLL_MS = 120_000;
const UPCOMING_PER_PAGE = 10;
const HISTORY_PER_PAGE = 25;

const EMPTY_UPCOMING: PaginatedMatchesResponse<UpcomingMatchWithOdds> = {
  items: [],
  page: 1,
  per_page: UPCOMING_PER_PAGE,
  total_items: 0,
  total_pages: 1,
  available_leagues: [],
};

const EMPTY_LIVE: PaginatedMatchesResponse<LiveMatchWithOdds> = {
  items: [],
  page: 1,
  per_page: 20,
  total_items: 0,
  total_pages: 1,
  available_leagues: [],
};

const EMPTY_ANALYTICS: ResultsAnalytics = {
  summary: {
    wins: 0,
    losses: 0,
    settled: 0,
    total_staked: 0,
    total_profit: 0,
    win_rate: 0,
    roi: 0,
  },
  cumulative_profit_data: [],
  outcome_data: [],
  league_profit_data: [],
  available_leagues: [],
};

const normalizeSelectedLeagues = (selected: Set<string>): string[] =>
  Array.from(selected).sort((a, b) => a.localeCompare(b));

const mergeUniqueUpcomingItems = (
  currentItems: UpcomingMatchWithOdds[],
  nextItems: UpcomingMatchWithOdds[],
): UpcomingMatchWithOdds[] => [
  ...currentItems,
  ...nextItems.filter((item) => !currentItems.some((existing) => existing.id === item.id)),
];

const overlayUpcomingItems = (
  baseItems: UpcomingMatchWithOdds[],
  overlayItems: UpcomingMatchWithOdds[],
): UpcomingMatchWithOdds[] => {
  const overlayById = new Map(overlayItems.map((item) => [item.id, item]));
  return baseItems.map((item) => overlayById.get(item.id) ?? item);
};

export const Home = () => {
  const [tab, setTab] = useState<TabEnum>(TabEnum.Upcoming);
  const [selectedEvents, setSelectedEvents] = useState<Set<string>>(new Set());
  const [filterPanelOpen, setFilterPanelOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [resultSelectedEvents, setResultSelectedEvents] = useState<Set<string>>(new Set());
  const [resultFilterPanelOpen, setResultFilterPanelOpen] = useState(false);
  const [resultSearchQuery, setResultSearchQuery] = useState("");
  const [analytics, setAnalytics] = useState<ResultsAnalytics>(EMPTY_ANALYTICS);
  const [resultsLoading, setResultsLoading] = useState(false);
  const [resultsError, setResultsError] = useState<string | null>(null);
  const [historyItems, setHistoryItems] = useState<Result[]>([]);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyTotalPages, setHistoryTotalPages] = useState(1);
  const [historyAvailableLeagues, setHistoryAvailableLeagues] = useState<string[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyLoadingMore, setHistoryLoadingMore] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [refreshClockMs, setRefreshClockMs] = useState<number>(() => Date.now());
  const [upcomingPage, setUpcomingPage] = useState(1);
  const [upcomingData, setUpcomingData] = useState(EMPTY_UPCOMING);
  const [upcomingLoading, setUpcomingLoading] = useState(true);
  const [upcomingLoadingMore, setUpcomingLoadingMore] = useState(false);
  const [upcomingError, setUpcomingError] = useState<string | null>(null);
  const [liveData, setLiveData] = useState(EMPTY_LIVE);
  const [liveLoading, setLiveLoading] = useState(true);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [expandedLiveMatchId, setExpandedLiveMatchId] = useState<number | null>(null);
  const [activePositionsBySeries, setActivePositionsBySeries] = useState<ActiveSeriesPositionGroup[]>([]);
  const [matchBettingStatuses, setMatchBettingStatuses] = useState<MatchBettingStatus[]>([]);
  const [sectionStatus, setSectionStatus] = useState<Record<string, SectionFreshnessStatus>>({});
  const [bankrollSummary, setBankrollSummary] = useState<BankrollSummary | null>(null);
  const upcomingSentinelRef = useRef<HTMLDivElement | null>(null);
  const historySentinelRef = useRef<HTMLDivElement | null>(null);
  const latestUpcomingQueryRef = useRef({
    searchQuery: "",
    selectedLeaguesLength: 0,
    upcomingPage: 1,
  });
  const latestLiveCountRef = useRef(0);
  const supportsIntersectionObserver =
    typeof window !== "undefined" && typeof window.IntersectionObserver === "function";

  const selectedLeagues = useMemo(() => normalizeSelectedLeagues(selectedEvents), [selectedEvents]);
  const resultSelectedLeagues = useMemo(
    () => normalizeSelectedLeagues(resultSelectedEvents),
    [resultSelectedEvents],
  );

  useEffect(() => {
    latestUpcomingQueryRef.current = {
      searchQuery,
      selectedLeaguesLength: selectedLeagues.length,
      upcomingPage,
    };
  }, [searchQuery, selectedLeagues.length, upcomingPage]);

  useEffect(() => {
    latestLiveCountRef.current = liveData.items.length;
  }, [liveData.items.length]);

  useEffect(() => {
    if (expandedLiveMatchId == null) return;
    const expandedMatchStillVisible = liveData.items.some(
      (match) => match.id === expandedLiveMatchId && match.stream_url,
    );
    if (!expandedMatchStillVisible) {
      setExpandedLiveMatchId(null);
    }
  }, [expandedLiveMatchId, liveData.items]);

  useEffect(() => {
    const id = window.setInterval(() => setRefreshClockMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timeoutId: number | null = null;
    const run = async (isInitial = false) => {
      if (isInitial) {
        setUpcomingLoading(true);
        setLiveLoading(true);
      }
      const { searchQuery } = latestUpcomingQueryRef.current;
      try {
        const [bootstrap, filteredUpcoming, filteredLive] = await Promise.all([
          fetchHomepageBootstrap(),
          fetchUpcomingWithOdds({
            perPage: UPCOMING_PER_PAGE,
            page: 1,
            tier: "s,a",
            search: searchQuery,
            leagues: selectedLeagues,
          }),
          fetchLiveWithOdds({
            perPage: 20,
            page: 1,
            search: searchQuery,
            leagues: selectedLeagues,
          }),
        ]);
        if (cancelled) return;
        const shouldUseBootstrapUpcoming =
          searchQuery.trim().length === 0 && selectedLeagues.length === 0;
        const nextUpcomingData = shouldUseBootstrapUpcoming
          ? {
              ...filteredUpcoming,
              items: overlayUpcomingItems(
                filteredUpcoming.items,
                bootstrap.upcoming.items ?? [],
              ),
            }
          : filteredUpcoming;
        setBankrollSummary(bootstrap.bankroll);
        setActivePositionsBySeries(bootstrap.active_positions_by_series ?? []);
        setMatchBettingStatuses(bootstrap.match_betting_statuses ?? []);
        setSectionStatus((bootstrap.section_status as Record<string, SectionFreshnessStatus> | undefined) ?? {});
        setUpcomingData(nextUpcomingData);
        setUpcomingError(null);
        setUpcomingPage(1);
        setLiveData(filteredLive);
        setLiveError(null);
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "Failed to load homepage data";
        if (isInitial) {
          setUpcomingError(message);
          setLiveError(message);
        }
      } finally {
        if (!cancelled && isInitial) {
          setUpcomingLoading(false);
          setLiveLoading(false);
        }
        if (!cancelled) {
          const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
          const delay = hidden
            ? BACKGROUND_POLL_MS
            : (tab === TabEnum.Upcoming && latestLiveCountRef.current > 0 ? LIVE_ACTIVE_POLL_MS : STANDARD_POLL_MS);
          timeoutId = window.setTimeout(() => {
            void run(false);
          }, delay);
        }
      }
    };
    void run(true);
    return () => {
      cancelled = true;
      if (timeoutId != null) window.clearTimeout(timeoutId);
    };
  }, [searchQuery, selectedLeagues, tab]);

  useEffect(() => {
    if (upcomingPage <= 1 || upcomingPage > upcomingData.total_pages) return;
    let cancelled = false;
    void fetchUpcomingWithOdds({
      perPage: UPCOMING_PER_PAGE,
      page: upcomingPage,
      tier: "s,a",
      search: searchQuery,
      leagues: selectedLeagues,
    })
      .then((data) => {
        if (cancelled) return;
        setUpcomingData((current) => ({
          ...current,
          ...data,
          items: mergeUniqueUpcomingItems(current.items, data.items),
        }));
        setUpcomingError(null);
      })
      .catch((error) => {
        if (cancelled) return;
        setUpcomingError(error instanceof Error ? error.message : "Failed to load matches");
      })
      .finally(() => {
        if (!cancelled) setUpcomingLoadingMore(false);
      });
    return () => {
      cancelled = true;
    };
  }, [searchQuery, selectedLeagues, upcomingData.total_pages, upcomingPage]);

  useEffect(() => {
    let cancelled = false;
    const run = (showLoader = true) => {
      if (showLoader) setResultsLoading(true);
      void fetchResultsAnalytics()
        .then((data) => {
          if (cancelled) return;
          setAnalytics(data);
          setResultsError(null);
        })
        .catch((error) => {
          if (cancelled) return;
          setResultsError(error instanceof Error ? error.message : "Failed to load analytics");
        })
        .finally(() => {
          if (!cancelled && showLoader) setResultsLoading(false);
        });
    };
    run(true);
    const id = window.setInterval(() => run(false), STANDARD_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void fetchBettingHistory({
      page: 1,
      perPage: HISTORY_PER_PAGE,
      search: resultSearchQuery,
      leagues: resultSelectedLeagues,
    })
      .then((data) => {
        if (cancelled) return;
        setHistoryItems(data.items);
        setHistoryPage(data.page);
        setHistoryTotalPages(data.total_pages);
        setHistoryAvailableLeagues(data.available_leagues ?? []);
      })
      .catch((error) => {
        if (cancelled) return;
        setHistoryError(error instanceof Error ? error.message : "Failed to load history");
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [resultSearchQuery, resultSelectedLeagues]);

  useEffect(() => {
    if (historyPage <= 1 || historyPage > historyTotalPages) return;
    let cancelled = false;
    void fetchBettingHistory({
      page: historyPage,
      perPage: HISTORY_PER_PAGE,
      search: resultSearchQuery,
      leagues: resultSelectedLeagues,
    })
      .then((data) => {
        if (cancelled) return;
        setHistoryItems((current) => [
          ...current,
          ...data.items.filter((item) => !current.some((existing) => existing.id === item.id)),
        ]);
        setHistoryTotalPages(data.total_pages);
        setHistoryAvailableLeagues(data.available_leagues ?? []);
      })
      .catch((error) => {
        if (cancelled) return;
        setHistoryError(error instanceof Error ? error.message : "Failed to load history");
      })
      .finally(() => {
        if (!cancelled) setHistoryLoadingMore(false);
      });
    return () => {
      cancelled = true;
    };
  }, [historyPage, historyTotalPages, resultSearchQuery, resultSelectedLeagues]);

  useEffect(() => {
    if (tab !== TabEnum.History || historyLoading || historyLoadingMore || historyPage >= historyTotalPages) {
      return;
    }
    if (!supportsIntersectionObserver) {
      return;
    }
    const node = historySentinelRef.current;
    if (!node) return;
    let observer: IntersectionObserver | null = null;
    observer = new IntersectionObserver((entries) => {
      const entry = entries[0];
      if (entry?.isIntersecting) {
        observer?.disconnect();
        setHistoryLoadingMore(true);
        setHistoryPage((current) => {
          if (current >= historyTotalPages) return current;
          return current + 1;
        });
      }
    }, { rootMargin: "160px" });
    observer.observe(node);
    return () => observer?.disconnect();
  }, [historyLoading, historyLoadingMore, historyPage, historyTotalPages, supportsIntersectionObserver, tab]);

  useEffect(() => {
    if (
      tab !== TabEnum.Upcoming ||
      upcomingLoading ||
      upcomingLoadingMore ||
      upcomingPage >= upcomingData.total_pages ||
      upcomingData.items.length === 0
    ) {
      return;
    }
    if (!supportsIntersectionObserver) {
      return;
    }
    const node = upcomingSentinelRef.current;
    if (!node) return;
    let observer: IntersectionObserver | null = null;
    observer = new IntersectionObserver((entries) => {
      const entry = entries[0];
      if (entry?.isIntersecting) {
        observer?.disconnect();
        setUpcomingLoadingMore(true);
        setUpcomingPage((current) => {
          if (current >= upcomingData.total_pages) return current;
          return current + 1;
        });
      }
    }, { rootMargin: "160px" });
    observer.observe(node);
    return () => observer?.disconnect();
  }, [
    supportsIntersectionObserver,
    tab,
    upcomingData.items.length,
    upcomingData.total_pages,
    upcomingLoading,
    upcomingLoadingMore,
    upcomingPage,
  ]);

  const matches = upcomingData.items;
  const liveMatches = liveData.items;
  const activeSeriesByMatchId = useMemo(() => {
    const next: Record<number, ActiveSeriesPositionGroup> = {};
    activePositionsBySeries.forEach((row) => {
      next[row.pandascore_match_id] = row;
    });
    return next;
  }, [activePositionsBySeries]);
  const matchBettingStatusByMatchId = useMemo(() => {
    const next: Record<number, MatchBettingStatus> = {};
    matchBettingStatuses.forEach((row) => {
      next[row.pandascore_match_id] = row;
    });
    return next;
  }, [matchBettingStatuses]);

  const eventOptions = useMemo(() => {
    return Array.from(new Set([
      ...(upcomingData.available_leagues ?? []),
      ...(liveData.available_leagues ?? []),
    ])).sort((a, b) => a.localeCompare(b));
  }, [
    liveData.available_leagues,
    upcomingData.available_leagues,
  ]);

  const resultEventOptions = useMemo(() => {
    return Array.from(
      new Set([
        ...analytics.available_leagues,
        ...historyAvailableLeagues,
      ]),
    ).sort((a, b) => a.localeCompare(b));
  }, [analytics.available_leagues, historyAvailableLeagues]);

  const resetUpcomingQueryState = () => {
    setUpcomingLoading(true);
    setUpcomingLoadingMore(false);
    setUpcomingError(null);
    setUpcomingData(EMPTY_UPCOMING);
    setUpcomingPage(1);
  };

  const resetHistoryQueryState = () => {
    setHistoryLoading(true);
    setHistoryLoadingMore(false);
    setHistoryError(null);
    setHistoryItems([]);
    setHistoryPage(1);
    setHistoryTotalPages(1);
  };

  const handleUpcomingSearchChange = (value: string) => {
    resetUpcomingQueryState();
    setSearchQuery(value);
  };

  const handleToggleEvent = (eventName: string) => {
    resetUpcomingQueryState();
    setSelectedEvents((previous) => {
      const next = new Set(previous);
      if (next.has(eventName)) next.delete(eventName);
      else next.add(eventName);
      return next;
    });
  };

  const handleClearFilter = () => {
    resetUpcomingQueryState();
    setSelectedEvents(new Set());
  };

  const handleResultSearchChange = (value: string) => {
    resetHistoryQueryState();
    setResultSearchQuery(value);
  };

  const handleToggleResultEvent = (eventName: string) => {
    resetHistoryQueryState();
    setResultSelectedEvents((previous) => {
      const next = new Set(previous);
      if (next.has(eventName)) next.delete(eventName);
      else next.add(eventName);
      return next;
    });
  };

  const canLoadMoreUpcoming =
    !upcomingLoading &&
    !upcomingLoadingMore &&
    !upcomingError &&
    upcomingPage < upcomingData.total_pages;
  const canLoadMoreHistory =
    !historyLoading &&
    !historyLoadingMore &&
    !historyError &&
    historyPage < historyTotalPages;

  const handleLoadMoreUpcoming = () => {
    setUpcomingLoadingMore(true);
    setUpcomingPage((current) => {
      if (current >= upcomingData.total_pages) return current;
      return current + 1;
    });
  };

  const handleLoadMoreHistory = () => {
    setHistoryLoadingMore(true);
    setHistoryPage((current) => {
      if (current >= historyTotalPages) return current;
      return current + 1;
    });
  };

  const handleToggleLiveStream = (match: LiveMatchWithOdds) => {
    if (!match.stream_url) return;
    setExpandedLiveMatchId((current) => (current === match.id ? null : match.id));
  };

  const preferredRefreshSection = tab === TabEnum.Upcoming && liveMatches.length > 0 ? "live" : "upcoming";
  const preferredRefreshMeta = sectionStatus[preferredRefreshSection] ?? null;
  const preferredRefreshAt = parseIsoDate(preferredRefreshMeta?.data_as_of ?? preferredRefreshMeta?.generated_at ?? null);
  const sectionName = preferredRefreshSection === "live" ? "Live" : "Upcoming";
  const refreshLabel = preferredRefreshMeta?.is_stale
    ? `${sectionName} sync delayed`
    : preferredRefreshAt !== null
      ? `${sectionName} updated ${formatLastRefreshAgo(preferredRefreshAt, refreshClockMs)}`
      : "";
  const refreshIsStale = Boolean(preferredRefreshMeta?.is_stale);

  return (
    <div className="flex flex-1 flex-col bg-concrete">
      <Header currentTab={tab} setTab={setTab} />

      <div className="flex-1 overflow-y-auto">
        <BankrollSummaryBar summary={bankrollSummary} />
        {tab === TabEnum.Upcoming && (
          <>
            {!upcomingLoading && !upcomingError && (matches.length > 0 || liveMatches.length > 0) && (
              <SearchFilterRefreshBar
                refreshLabel={refreshLabel}
                refreshIsStale={refreshIsStale}
                filterPanelOpen={filterPanelOpen}
                onToggleFilterPanel={() => setFilterPanelOpen((open) => !open)}
                onCloseFilterPanel={() => setFilterPanelOpen(false)}
                selectedCount={selectedEvents.size}
                searchValue={searchQuery}
                onSearchChange={handleUpcomingSearchChange}
                searchPlaceholder="SEARCH TEAMS OR EVENTS..."
                searchAriaLabel="Search matches"
                eventOptions={eventOptions}
                selectedEvents={selectedEvents}
                onToggleEvent={handleToggleEvent}
                onClearFilter={handleClearFilter}
              />
            )}
            {upcomingLoading && (
              <div className="p-8 text-center text-taupe">Loading upcoming matches…</div>
            )}
            {upcomingError && (
              <div className="p-8 text-center text-error">{upcomingError}</div>
            )}
            {!upcomingLoading && !upcomingError && matches.length === 0 && liveMatches.length === 0 && (
              <div className="p-8 text-center text-taupe">No upcoming matches at the moment.</div>
            )}
            {!upcomingLoading && !upcomingError && (matches.length > 0 || liveMatches.length > 0) && (
              <>
                <section className="border-b border-soulsilver/50">
                  <h2 className="bg-deepdark/50 px-4 py-2 text-sm font-medium uppercase tracking-wide text-gold">
                    Live now
                  </h2>
                  {liveLoading ? (
                    <div className="p-4 text-center text-sm text-taupe">Loading live…</div>
                  ) : liveError ? (
                    <div className="p-4 text-center text-sm text-error">{liveError}</div>
                  ) : liveMatches.length === 0 ? (
                    <div className="bg-deepdark p-6 text-center text-sm uppercase tracking-wide text-taupe">
                      No live matches
                    </div>
                  ) : (
                    <>
                      <div className="hidden md:block">
                        <LiveMatchTable
                          matches={liveMatches}
                          activeSeriesByMatchId={activeSeriesByMatchId}
                          matchBettingStatusByMatchId={matchBettingStatusByMatchId}
                          expandedMatchId={expandedLiveMatchId}
                          onToggleStream={handleToggleLiveStream}
                        />
                      </div>
                      <div className="divide-y divide-concrete md:hidden">
                        {liveMatches.map((match) => (
                          <LiveMatchCard
                            key={match.id}
                            match={match}
                            activeSeries={activeSeriesByMatchId[match.id]}
                          />
                        ))}
                      </div>
                    </>
                  )}
                </section>
                <section>
                  <h2 className="bg-deepdark/30 px-4 py-2 text-sm font-medium uppercase tracking-wide text-cream">
                    Upcoming
                  </h2>
                  {matches.length === 0 ? (
                    <div className="bg-deepdark p-6 text-center text-sm uppercase tracking-wide text-taupe">
                      No upcoming matches for the selected filters.
                    </div>
                  ) : (
                    <>
                      <div className="hidden md:block">
                        <UpcomingWithOddsTable
                          matches={matches}
                          activeSeriesByMatchId={activeSeriesByMatchId}
                          matchBettingStatusByMatchId={matchBettingStatusByMatchId}
                        />
                      </div>
                      <div className="divide-y divide-concrete md:hidden">
                        {matches.map((match) => (
                          <UpcomingMatchCard
                            key={match.id}
                            match={match}
                            activeSeries={activeSeriesByMatchId[match.id]}
                            matchBettingStatus={matchBettingStatusByMatchId[match.id]}
                          />
                        ))}
                      </div>
                      {supportsIntersectionObserver ? (
                        <div ref={upcomingSentinelRef} className="h-8" aria-hidden />
                      ) : null}
                      {!supportsIntersectionObserver && canLoadMoreUpcoming && (
                        <div className="border-t border-concrete/50 bg-deepdark px-4 py-4">
                          <button
                            type="button"
                            onClick={handleLoadMoreUpcoming}
                            className="w-full rounded border border-gold bg-gold/10 px-4 py-3 text-sm font-semibold uppercase tracking-wide text-gold hover:bg-gold/20 focus:outline-none focus:ring-2 focus:ring-gold focus:ring-offset-2 focus:ring-offset-deepdark"
                          >
                            Load more matches
                          </button>
                        </div>
                      )}
                      {upcomingLoadingMore && (
                        <div className="p-4 text-center text-sm text-taupe">Loading more upcoming matches…</div>
                      )}
                    </>
                  )}
                </section>
              </>
            )}
          </>
        )}
        {tab === TabEnum.Results && (
          <>
            {resultsLoading && (
              <div className="p-8 text-center text-taupe">Loading analytics…</div>
            )}
            {resultsError && (
              <div className="p-8 text-center text-error">{resultsError}</div>
            )}
            {!resultsLoading && !resultsError && analytics.summary.settled === 0 && (
              <div className="p-8 text-center text-taupe">NO SETTLED BETS YET</div>
            )}
            {!resultsLoading && !resultsError && analytics.summary.settled > 0 && (
              <div className="min-h-full">
                <ResultsMetrics analytics={analytics} />
              </div>
            )}
          </>
        )}
        {tab === TabEnum.History && (
          <>
            <SearchFilterRefreshBar
              filterPanelOpen={resultFilterPanelOpen}
              onToggleFilterPanel={() => setResultFilterPanelOpen((open) => !open)}
              onCloseFilterPanel={() => setResultFilterPanelOpen(false)}
              selectedCount={resultSelectedEvents.size}
              searchValue={resultSearchQuery}
              onSearchChange={handleResultSearchChange}
              searchPlaceholder="SEARCH TEAMS OR EVENTS..."
              searchAriaLabel="Search history"
              eventOptions={resultEventOptions}
              selectedEvents={resultSelectedEvents}
              onToggleEvent={handleToggleResultEvent}
              onClearFilter={() => {
                resetHistoryQueryState();
                setResultSelectedEvents(new Set());
              }}
            />
            {historyLoading && (
              <div className="p-8 text-center text-taupe">Loading settled bets…</div>
            )}
            {historyError && (
              <div className="p-8 text-center text-error">{historyError}</div>
            )}
            {!historyLoading && !historyError && historyItems.length === 0 && (
              <div className="p-8 text-center text-taupe">NO SETTLED BETS YET</div>
            )}
            {!historyLoading && !historyError && historyItems.length > 0 && (
              <>
                <ResultTable results={historyItems} />
                {supportsIntersectionObserver ? (
                  <div ref={historySentinelRef} className="h-8" aria-hidden />
                ) : null}
                {!supportsIntersectionObserver && canLoadMoreHistory && (
                  <div className="border-t border-concrete/50 bg-deepdark px-4 py-4">
                    <button
                      type="button"
                      onClick={handleLoadMoreHistory}
                      className="w-full rounded border border-gold bg-gold/10 px-4 py-3 text-sm font-semibold uppercase tracking-wide text-gold hover:bg-gold/20 focus:outline-none focus:ring-2 focus:ring-gold focus:ring-offset-2 focus:ring-offset-deepdark"
                    >
                      Load more history
                    </button>
                  </div>
                )}
                {historyLoadingMore && (
                  <div className="p-4 text-center text-sm text-taupe">Loading more history…</div>
                )}
              </>
            )}
          </>
        )}
        {tab === TabEnum.PowerRankings && <PowerRankingsTable />}
      </div>
    </div>
  );
};
