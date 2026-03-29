import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PowerRankingCard } from "./UI/PowerRankingCard/PowerRankingCard";
import type { PowerRankingRow } from "../types/PowerRanking";

const row: PowerRankingRow = {
  rank: 1,
  team: "Hanwha Life Esports",
  league_slug: "lck",
  wins: 12,
  losses: 3,
  win_rate: 0.8,
  avg_game_duration_min: 31.2,
  avg_gold_diff_15: 845,
  first_blood_pct: 0.62,
  first_dragon_pct: 0.7,
  first_tower_pct: 0.66,
  games_played: 15,
};

describe("power rankings rendering", () => {
  it("shows the full team name without an abbreviation label", () => {
    render(<PowerRankingCard row={row} />);

    expect(screen.getByText("Hanwha Life Esports")).toBeInTheDocument();
    expect(screen.queryByText("HLE")).not.toBeInTheDocument();
  });
});
