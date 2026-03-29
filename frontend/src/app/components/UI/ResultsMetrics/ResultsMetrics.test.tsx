import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { resultsAnalyticsFixture } from "@/test/fixtures";
import { ResultsMetrics } from "./ResultsMetrics";

vi.mock("recharts", () => {
  const MockWrapper = ({ children }: { children?: ReactNode }) => <div>{children}</div>;

  return {
    ResponsiveContainer: MockWrapper,
    LineChart: MockWrapper,
    BarChart: MockWrapper,
    PieChart: MockWrapper,
    CartesianGrid: () => null,
    XAxis: () => null,
    YAxis: () => null,
    Tooltip: () => null,
    Legend: () => null,
    Line: () => null,
    Pie: MockWrapper,
    Bar: MockWrapper,
    Cell: () => null,
  };
});

describe("ResultsMetrics", () => {
  it("renders the desktop profit-by-event chart section when league data exists", () => {
    render(<ResultsMetrics analytics={resultsAnalyticsFixture} />);

    expect(screen.getByText(/profit by event/i)).toBeInTheDocument();
    expect(screen.queryByText(/no settled event profit yet/i)).not.toBeInTheDocument();
  });

  it("shows a fallback message when no league profit data is available", () => {
    render(
      <ResultsMetrics
        analytics={{
          ...resultsAnalyticsFixture,
          league_profit_data: [],
        }}
      />,
    );

    expect(screen.getByText(/profit by event/i)).toBeInTheDocument();
    expect(screen.getByText(/no settled event profit yet/i)).toBeInTheDocument();
  });
});
