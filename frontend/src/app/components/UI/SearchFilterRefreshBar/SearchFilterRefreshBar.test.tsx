import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SearchFilterRefreshBar } from "./SearchFilterRefreshBar";

describe("SearchFilterRefreshBar", () => {
  it("renders passive refresh metadata and forwards user interactions", () => {
    const onToggleFilterPanel = vi.fn();
    const onCloseFilterPanel = vi.fn();
    const onSearchChange = vi.fn();
    const onToggleEvent = vi.fn();
    const onClearFilter = vi.fn();

    render(
      <SearchFilterRefreshBar
        refreshLabel="Live updated 2m ago"
        filterPanelOpen={false}
        onToggleFilterPanel={onToggleFilterPanel}
        onCloseFilterPanel={onCloseFilterPanel}
        selectedCount={2}
        searchValue=""
        onSearchChange={onSearchChange}
        searchPlaceholder="SEARCH TEAMS OR EVENTS..."
        searchAriaLabel="Search matches"
        eventOptions={["LCK", "LEC"]}
        selectedEvents={new Set()}
        onToggleEvent={onToggleEvent}
        onClearFilter={onClearFilter}
      />,
    );

    expect(screen.getByText(/live updated 2m ago/i)).toBeInTheDocument();
    expect(screen.queryByText(/next refresh/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox", { name: /search matches/i }), {
      target: { value: "alpha" },
    });
    fireEvent.click(screen.getByRole("button", { name: /filter by event/i }));

    expect(onSearchChange).toHaveBeenCalledWith("alpha");
    expect(onToggleFilterPanel).toHaveBeenCalledTimes(1);
  });

  it("omits refresh metadata when no refresh label is provided", () => {
    render(
      <SearchFilterRefreshBar
        filterPanelOpen={false}
        onToggleFilterPanel={() => {}}
        onCloseFilterPanel={() => {}}
        selectedCount={0}
        searchValue=""
        onSearchChange={() => {}}
        searchPlaceholder="SEARCH TEAMS OR EVENTS..."
        searchAriaLabel="Search results"
        eventOptions={["LCK"]}
        selectedEvents={new Set()}
        onToggleEvent={() => {}}
        onClearFilter={() => {}}
      />,
    );

    expect(screen.queryByText(/updated/i)).not.toBeInTheDocument();
  });
});
