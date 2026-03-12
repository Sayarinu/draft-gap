"use client";

import { EventFilterPanel } from "@/app/components/UI/EventFilterPanel/EventFilterPanel";

interface SearchFilterRefreshBarProps {
  onRefresh: () => void;
  isRefreshing: boolean;
  refreshProgress?: number;
  refreshStageLabel?: string;
  refreshButtonDisabled?: boolean;
  nextRefreshLabel?: string;
  filterPanelOpen: boolean;
  onToggleFilterPanel: () => void;
  onCloseFilterPanel: () => void;
  selectedCount: number;
  searchValue: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder: string;
  searchAriaLabel: string;
  eventOptions: string[];
  selectedEvents: Set<string>;
  onToggleEvent: (eventName: string) => void;
  onClearFilter: () => void;
}

interface ToolbarIconProps {
  className?: string;
}

const EventFilterIcon = ({ className }: ToolbarIconProps) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    aria-hidden
  >
    <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
  </svg>
);

const RefreshIcon = ({ className }: ToolbarIconProps) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    aria-hidden
  >
    <polyline points="23 4 23 10 17 10" />
    <polyline points="1 20 1 14 7 14" />
    <path d="M3.51 9a9 9 0 0 1 14.13-3.36L23 10M1 14l5.36 4.36A9 9 0 0 0 20.49 15" />
  </svg>
);

export const SearchFilterRefreshBar = ({
  onRefresh,
  isRefreshing,
  refreshProgress = 0,
  refreshStageLabel = "",
  refreshButtonDisabled = false,
  nextRefreshLabel = "",
  filterPanelOpen,
  onToggleFilterPanel,
  onCloseFilterPanel,
  selectedCount,
  searchValue,
  onSearchChange,
  searchPlaceholder,
  searchAriaLabel,
  eventOptions,
  selectedEvents,
  onToggleEvent,
  onClearFilter,
}: SearchFilterRefreshBarProps) => {
  const isRefreshDisabled = isRefreshing || refreshButtonDisabled;
  const refreshTitle = isRefreshing
    ? "Refreshing..."
    : nextRefreshLabel || "Refresh data";
  const showLockMessage = refreshButtonDisabled && !isRefreshing && Boolean(nextRefreshLabel);
  const safeProgress = Math.max(0, Math.min(100, Math.round(refreshProgress)));

  return (
    <div className="border-b border-soulsilver/50 bg-deepdark/30">
      <div className="relative flex items-center gap-2 px-4 py-2">
        <button
          type="button"
          onClick={onRefresh}
          className="flex items-center justify-center rounded border border-coffee bg-deepdark p-2 text-cream focus:outline-none focus:ring-1 focus:ring-gold shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label={refreshTitle}
          title={refreshTitle}
          disabled={isRefreshDisabled}
        >
          <RefreshIcon
            className={`h-4 w-4 shrink-0 ${isRefreshing ? "animate-spin text-gold" : ""}`}
            aria-hidden
          />
        </button>
        {showLockMessage && (
          <span className="text-2xs text-error whitespace-nowrap font-semibold uppercase tracking-wide">
            Refresh locked
          </span>
        )}
        {nextRefreshLabel && !isRefreshing && (
          <span className="text-2xs text-taupe whitespace-nowrap">{nextRefreshLabel}</span>
        )}
        <button
          type="button"
          onClick={onToggleFilterPanel}
          className="relative flex items-center justify-center rounded border border-coffee bg-deepdark p-2 text-cream focus:outline-none focus:ring-1 focus:ring-gold shrink-0"
          aria-label="Filter by event"
          aria-expanded={filterPanelOpen}
        >
          <EventFilterIcon className="h-4 w-4 shrink-0" aria-hidden />
          {selectedCount > 0 && (
            <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-gold px-1 text-2xs font-semibold text-deepdark">
              {selectedCount}
            </span>
          )}
        </button>
        <input
          type="search"
          value={searchValue}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={searchPlaceholder}
          className="flex-1 rounded border border-coffee bg-deepdark px-3 py-1.5 text-sm text-cream placeholder-taupe focus:outline-none focus:ring-1 focus:ring-gold"
          aria-label={searchAriaLabel}
        />
        <EventFilterPanel
          isOpen={filterPanelOpen}
          onClose={onCloseFilterPanel}
          eventOptions={eventOptions}
          selectedEvents={selectedEvents}
          onToggleEvent={onToggleEvent}
          onClearAll={onClearFilter}
        />
      </div>
      {isRefreshing && (
        <div className="px-4 pb-2">
          <div className="flex items-center justify-between text-2xs text-taupe mb-1 uppercase tracking-wide">
            <span>{refreshStageLabel || "Refreshing..."}</span>
            <span className="font-mono text-cream">{safeProgress}%</span>
          </div>
          <div className="h-1.5 w-full rounded bg-coffee/60 overflow-hidden">
            <div
              className="h-full bg-gold transition-all duration-500"
              style={{ width: `${safeProgress}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
};
