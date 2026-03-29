import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BankrollSummaryBar } from "./BankrollSummaryBar";

describe("BankrollSummaryBar", () => {
  it("renders bankroll metrics without the change field", () => {
    render(
      <BankrollSummaryBar
        summary={{
          initial_balance: 1000,
          current_balance: 1110,
          win_rate_pct: 60,
          total_profit: 110,
          roi_pct: 44,
        }}
      />,
    );

    expect(screen.getByText(/bankroll/i)).toBeInTheDocument();
    expect(screen.queryByText(/change/i)).not.toBeInTheDocument();
    expect(screen.getByText(/\$1110\.00/i)).toBeInTheDocument();
  });

  it("renders a loading state when no summary is available", () => {
    render(<BankrollSummaryBar summary={null} />);

    expect(screen.getByText(/loading bankroll/i)).toBeInTheDocument();
  });
});
