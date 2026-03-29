import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/test/server";
import {
  homepageBootstrapFixture,
  livePaginatedFixture,
  powerRankingsFixture,
  upcomingMatchesFixture,
  upcomingPaginatedFixture,
} from "@/test/fixtures";
import { Home } from "./page";

vi.mock("./components/UI/ResultsMetrics/ResultsMetrics", () => ({
  ResultsMetrics: () => <div>Results metrics</div>,
}));

describe("Home", () => {
  it("renders upcoming and live data and filters matches by search input", async () => {
    render(<Home />);

    expect((await screen.findAllByText("ALPHA")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("DELTA").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1.90").length).toBeGreaterThan(0);
    expect(screen.queryByText(/page 1 of 2/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox", { name: /search matches/i }), {
      target: { value: "delta" },
    });

    await waitFor(() => {
      expect(screen.getAllByText("DELTA").length).toBeGreaterThan(0);
      expect(screen.queryByText("ALPHA")).not.toBeInTheDocument();
    });
  });

  it("loads more upcoming matches with infinite scroll and hides pager controls", async () => {
    Object.defineProperty(window, "IntersectionObserver", {
      configurable: true,
      writable: true,
      value: vi.fn().mockImplementation((callback: IntersectionObserverCallback) => ({
        observe: vi.fn(() => {
          callback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
        }),
        unobserve: vi.fn(),
        disconnect: vi.fn(),
        takeRecords: vi.fn(),
        root: null,
        rootMargin: "",
        thresholds: [],
      })),
    });

    server.use(
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/homepage\/bootstrap(?:\?.*)?$/, () => {
        return HttpResponse.json({
          ...homepageBootstrapFixture,
          upcoming: {
            ...homepageBootstrapFixture.upcoming,
            items: [upcomingMatchesFixture[0]],
            total_items: 2,
            total_pages: 2,
          },
        });
      }),
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/pandascore\/lol\/upcoming-with-odds(?:\?.*)?$/, ({ request }) => {
        const url = new URL(request.url);
        const page = Number(url.searchParams.get("page") ?? "1");
        if (page === 1) {
          return HttpResponse.json({
            ...upcomingPaginatedFixture,
            items: [upcomingMatchesFixture[0]],
            total_items: 2,
            total_pages: 2,
          });
        }
        return HttpResponse.json({
          ...upcomingPaginatedFixture,
          page: 2,
          items: [upcomingMatchesFixture[1]],
          total_items: 2,
          total_pages: 2,
        });
      }),
    );

    render(<Home />);

    expect((await screen.findAllByText("ALPHA")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("DELTA")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /previous/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /next/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/page 1 of 2/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/total upcoming matches/i)).not.toBeInTheDocument();
  });

  it("falls back to a load-more button when IntersectionObserver is unavailable", async () => {
    Object.defineProperty(window, "IntersectionObserver", {
      configurable: true,
      writable: true,
      value: undefined,
    });

    server.use(
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/homepage\/bootstrap(?:\?.*)?$/, () => {
        return HttpResponse.json({
          ...homepageBootstrapFixture,
          upcoming: {
            ...homepageBootstrapFixture.upcoming,
            items: [upcomingMatchesFixture[0]],
            total_items: 2,
            total_pages: 2,
          },
          live: {
            ...homepageBootstrapFixture.live,
            items: [],
            total_items: 0,
            total_pages: 1,
          },
        });
      }),
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/pandascore\/lol\/upcoming-with-odds(?:\?.*)?$/, ({ request }) => {
        const url = new URL(request.url);
        const page = Number(url.searchParams.get("page") ?? "1");
        if (page === 1) {
          return HttpResponse.json({
            ...upcomingPaginatedFixture,
            items: [upcomingMatchesFixture[0]],
            total_items: 2,
            total_pages: 2,
          });
        }
        return HttpResponse.json({
          ...upcomingPaginatedFixture,
          page: 2,
          items: [upcomingMatchesFixture[1]],
          total_items: 2,
          total_pages: 2,
        });
      }),
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/pandascore\/lol\/live-with-odds(?:\?.*)?$/, () => {
        return HttpResponse.json({
          ...livePaginatedFixture,
          items: [],
          total_items: 0,
          total_pages: 1,
          available_leagues: [],
        });
      }),
    );

    render(<Home />);

    expect((await screen.findAllByText("ALPHA")).length).toBeGreaterThan(0);

    const loadMoreButton = await screen.findByRole("button", { name: /load more matches/i });
    fireEvent.click(loadMoreButton);

    expect((await screen.findAllByText("DELTA")).length).toBeGreaterThan(0);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /load more matches/i })).not.toBeInTheDocument();
    });
  });

  it("shows passive refresh status in the toolbar without an orphaned-bets section", async () => {
    render(<Home />);

    expect((await screen.findAllByText(/updated/i)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/next refresh/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/active bets not in schedule/i)).not.toBeInTheDocument();
  });

  it("opens the desktop live stream inline and preserves the mobile external link", async () => {
    render(<Home />);

    fireEvent.click(await screen.findByRole("button", { name: /watch/i }));

    expect(await screen.findByTitle(/alpha vs beta stream/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open in new tab/i })).toHaveAttribute(
      "href",
      "https://player.example.com/alpha-beta",
    );

    const watchLinks = screen.getAllByRole("link", { name: /^watch$/i });
    expect(watchLinks.length).toBeGreaterThan(0);
    expect(watchLinks[0]).toHaveAttribute("href", "https://player.example.com/alpha-beta");
  });

  it("loads settled results when the results tab is selected", async () => {
    render(<Home />);

    fireEvent.click(screen.getAllByRole("button", { name: "Results" })[0]);

    expect(await screen.findByText("Results metrics")).toBeInTheDocument();
    expect(screen.queryByText("Alpha vs Beta")).not.toBeInTheDocument();
    expect(screen.queryByText(/updated/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/next refresh/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("searchbox", { name: /search results/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /filter by event/i })).not.toBeInTheDocument();
  });

  it("loads settled bet history in the history tab", async () => {
    render(<Home />);

    fireEvent.click(screen.getAllByRole("button", { name: "History" })[0]);

    expect((await screen.findAllByText("Alpha vs Beta")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Delta vs Echo").length).toBeGreaterThan(0);
    expect(screen.queryByText(/settled bets loaded/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/updated/i)).not.toBeInTheDocument();
  });

  it("keeps a single stable bankroll value across tab switches", async () => {
    render(<Home />);

    expect(await screen.findByText(/\$1110\.00/i)).toBeInTheDocument();
    expect(screen.getAllByText(/\$1110\.00/i)).toHaveLength(1);

    fireEvent.click(screen.getAllByRole("button", { name: "Results" })[0]);
    expect(await screen.findByText(/\$1110\.00/i)).toBeInTheDocument();
    expect(screen.getAllByText(/\$1110\.00/i)).toHaveLength(1);

    fireEvent.click(screen.getAllByRole("button", { name: "History" })[0]);
    expect(await screen.findByText(/\$1110\.00/i)).toBeInTheDocument();
    expect(screen.getAllByText(/\$1110\.00/i)).toHaveLength(1);

    fireEvent.click(screen.getAllByRole("button", { name: "Matches" })[0]);
    expect(await screen.findByText(/\$1110\.00/i)).toBeInTheDocument();
    expect(screen.getAllByText(/\$1110\.00/i)).toHaveLength(1);
  });

  it("does not replace the initial bankroll value after bootstrap when bankroll endpoint differs", async () => {
    server.use(
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/homepage\/bootstrap(?:\?.*)?$/, () => {
        return HttpResponse.json({
          ...homepageBootstrapFixture,
          bankroll: {
            ...homepageBootstrapFixture.bankroll,
            current_balance: 1110,
          },
        });
      }),
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/betting\/bankroll(?:\?.*)?$/, () => {
        return HttpResponse.json({
          ...homepageBootstrapFixture.bankroll,
          current_balance: 999,
        });
      }),
    );

    render(<Home />);

    expect(await screen.findByText(/\$1110\.00/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.queryByText(/\$999\.00/i)).not.toBeInTheDocument();
    });
  });

  it("does not render pending betting status copy in the main table when there is no placed bet", async () => {
    server.use(
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/homepage\/bootstrap(?:\?.*)?$/, () => {
        return HttpResponse.json({
          ...homepageBootstrapFixture,
          active_bets: [],
          active_positions_by_series: [],
          match_betting_statuses: [
            {
              pandascore_match_id: 1001,
              status: "pending_force_bet",
              reason_code: "eligible_force_bet",
              within_force_window: true,
              force_bet_after: "2026-03-22T16:00:00Z",
            },
          ],
        });
      }),
    );

    render(<Home />);

    expect((await screen.findAllByText(/alpha/i)).length).toBeGreaterThan(0);
    await waitFor(() => {
      expect(screen.queryByText(/pending · force bet/i)).not.toBeInTheDocument();
    });
  });

  it("loads full power rankings without rendering the homepage preview first", async () => {
    let releaseResponse: (() => void) | null = null;
    const rankingsRequest = new Promise<void>((resolve) => {
      releaseResponse = resolve;
    });

    server.use(
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/homepage\/bootstrap(?:\?.*)?$/, () => {
        return HttpResponse.json({
          ...homepageBootstrapFixture,
          power_rankings_preview: [
            {
              ...homepageBootstrapFixture.power_rankings_preview[0],
              team: "Preview Only",
            },
          ],
        });
      }),
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/rankings\/power(?:\?.*)?$/, async () => {
        await rankingsRequest;
        return HttpResponse.json(powerRankingsFixture);
      }),
    );

    render(<Home />);

    fireEvent.click(screen.getAllByRole("button", { name: "Power Rankings" })[0]);

    expect(await screen.findByText(/loading power rankings/i)).toBeInTheDocument();
    expect(screen.queryByText("Preview Only")).not.toBeInTheDocument();

    releaseResponse?.();

    expect(await screen.findByText("Full Power")).toBeInTheDocument();
    expect(screen.queryByText("Preview Only")).not.toBeInTheDocument();
  });

  it("shows a friendly backend error when odds requests fail", async () => {
    server.use(
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/homepage\/bootstrap(?:\?.*)?$/, () => {
        return new HttpResponse(null, { status: 503 });
      }),
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/pandascore\/lol\/upcoming-with-odds(?:\?.*)?$/, () => {
        return new HttpResponse(null, { status: 503 });
      }),
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/pandascore\/lol\/live-with-odds(?:\?.*)?$/, () => {
        return new HttpResponse(null, { status: 503 });
      }),
    );

    render(<Home />);

    expect(
      await screen.findByText(/server temporarily unavailable/i),
    ).toBeInTheDocument();
  });

  it("builds event filter options from available league metadata across all pages", async () => {
    server.use(
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/homepage\/bootstrap(?:\?.*)?$/, () => {
        return HttpResponse.json({
          ...homepageBootstrapFixture,
          upcoming: {
            ...homepageBootstrapFixture.upcoming,
            available_leagues: ["LCK", "LPL"],
          },
          live: {
            ...homepageBootstrapFixture.live,
            available_leagues: ["LCK"],
          },
        });
      }),
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/pandascore\/lol\/upcoming-with-odds(?:\?.*)?$/, () => {
        return HttpResponse.json({
          ...upcomingPaginatedFixture,
          items: [
            {
              ...upcomingPaginatedFixture.items[0],
              league_name: "EWC",
            },
          ],
          available_leagues: ["EWC", "LPL"],
          total_items: 1,
          total_pages: 1,
        });
      }),
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/pandascore\/lol\/live-with-odds(?:\?.*)?$/, () => {
        return HttpResponse.json({
          ...livePaginatedFixture,
          available_leagues: ["LCK"],
        });
      }),
    );

    render(<Home />);

    await screen.findByRole("button", { name: /filter by event/i });

    fireEvent.click(screen.getByRole("button", { name: /filter by event/i }));

    const dialog = await screen.findByRole("dialog", { name: /filter by event/i });
    expect(within(dialog).getByText("LPL")).toBeInTheDocument();
    expect(within(dialog).getByText("EWC")).toBeInTheDocument();
    expect(within(dialog).queryByText("NACL")).not.toBeInTheDocument();
  });

  it("does not render hidden leagues from homepage bootstrap on first load", async () => {
    server.use(
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/homepage\/bootstrap(?:\?.*)?$/, () => {
        return HttpResponse.json({
          ...homepageBootstrapFixture,
          upcoming: {
            ...homepageBootstrapFixture.upcoming,
            items: [
              {
                ...upcomingMatchesFixture[0],
                league_name: "VCS",
                team1_name: "Hidden One",
                team2_name: "Hidden Two",
              },
              {
                ...upcomingMatchesFixture[1],
                league_name: "LEC",
                team1_name: "Visible One",
                team2_name: "Visible Two",
              },
            ],
            available_leagues: ["VCS", "LEC"],
            total_items: 2,
            total_pages: 1,
          },
        });
      }),
      http.get(/^(?:http:\/\/localhost:8000)?\/api\/v1\/pandascore\/lol\/upcoming-with-odds(?:\?.*)?$/, () => {
        return HttpResponse.json({
          ...upcomingPaginatedFixture,
          items: [
            {
              ...upcomingMatchesFixture[1],
              league_name: "LEC",
              team1_name: "Visible One",
              team2_name: "Visible Two",
            },
          ],
          available_leagues: ["LEC"],
          total_items: 1,
          total_pages: 1,
        });
      }),
    );

    render(<Home />);

    expect((await screen.findAllByText("VISIBLE ONE")).length).toBeGreaterThan(0);
    expect(screen.queryByText("HIDDEN ONE")).not.toBeInTheDocument();
    expect(screen.queryByText("VCS")).not.toBeInTheDocument();
  });

  it("does not render waiting-for-better-odds copy for tracked upcoming matches", async () => {
    render(<Home />);

    expect((await screen.findAllByText(/alpha/i)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/waiting · better price/i)).not.toBeInTheDocument();
  });
});
