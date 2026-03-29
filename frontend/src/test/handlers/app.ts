import { http, HttpResponse } from "msw";

import {
  activeBetsFixture,
  bankrollSummaryFixture,
  homepageBootstrapFixture,
  livePaginatedFixture,
  oddsRefreshGlobalStatusFixture,
  powerRankingsFixture,
  resultsAnalyticsFixture,
  resultsHistoryFixture,
  upcomingPaginatedFixture,
} from "../fixtures";

const apiPath = (path: string): RegExp => {
  const escapedPath = path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`^(?:http://localhost:8000)?${escapedPath}(?:\\?.*)?$`);
};

export const appHandlers = [
  http.get(apiPath("/api/v1/homepage/bootstrap"), () => {
    return HttpResponse.json(homepageBootstrapFixture);
  }),
  http.get(apiPath("/api/v1/pandascore/lol/upcoming-with-odds"), ({ request }) => {
    const url = new URL(request.url);
    const search = (url.searchParams.get("search") ?? "").toLowerCase();
    const filteredItems = !search
      ? upcomingPaginatedFixture.items
      : upcomingPaginatedFixture.items.filter((match) =>
          [match.league_name, match.team1_name, match.team2_name]
            .some((part) => part.toLowerCase().includes(search)),
        );
    return HttpResponse.json({
      ...upcomingPaginatedFixture,
      items: filteredItems,
      total_items: filteredItems.length,
      total_pages: search ? 1 : upcomingPaginatedFixture.total_pages,
    });
  }),
  http.get(apiPath("/api/v1/pandascore/lol/live-with-odds"), ({ request }) => {
    const url = new URL(request.url);
    const search = (url.searchParams.get("search") ?? "").toLowerCase();
    const filteredItems = !search
      ? livePaginatedFixture.items
      : livePaginatedFixture.items.filter((match) =>
          [match.league_name, match.team1_name, match.team2_name]
            .some((part) => part.toLowerCase().includes(search)),
        );
    return HttpResponse.json({
      ...livePaginatedFixture,
      items: filteredItems,
      total_items: filteredItems.length,
      total_pages: 1,
    });
  }),
  http.get(apiPath("/api/v1/pandascore/odds-refresh-global-status"), () => {
    return HttpResponse.json(oddsRefreshGlobalStatusFixture);
  }),
  http.get(apiPath("/api/v1/betting/bankroll"), () => {
    return HttpResponse.json(bankrollSummaryFixture);
  }),
  http.get(apiPath("/api/v1/betting/bets/active"), () => {
    return HttpResponse.json(activeBetsFixture);
  }),
  http.get(apiPath("/api/v1/betting/bets/open-status"), () => {
    return HttpResponse.json([]);
  }),
  http.get(apiPath("/api/v1/betting/results"), () => {
    return HttpResponse.json(resultsHistoryFixture);
  }),
  http.get(apiPath("/api/v1/betting/results/analytics"), () => {
    return HttpResponse.json(resultsAnalyticsFixture);
  }),
  http.get(apiPath("/api/v1/rankings/power"), () => {
    return HttpResponse.json(powerRankingsFixture);
  }),
];
