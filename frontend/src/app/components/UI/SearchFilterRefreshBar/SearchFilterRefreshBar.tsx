"use client";

import { EventFilterPanel } from "@/app/components/UI/EventFilterPanel/EventFilterPanel";

interface SearchFilterRefreshBarProps {
  refreshLabel?: string;
  refreshIsStale?: boolean;
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

const EventFilterIcon = ({ className }: { className?: string }) => (
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

export const SearchFilterRefreshBar = ({
  refreshLabel = "",
  refreshIsStale = false,
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
  const showRefreshMetadata = refreshLabel !== "";

  return (
    <div className="border-b border-soulsilver/50 bg-deepdark/30">
      <div className="relative flex flex-wrap items-center gap-2 px-3 py-2 sm:px-4">
        <div className="flex min-w-0 shrink-0 items-center gap-1 sm:gap-2">
          <button
            type="button"
            onClick={onToggleFilterPanel}
            className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded border border-coffee bg-deepdark text-cream focus:outline-none focus:ring-1 focus:ring-gold sm:h-auto sm:w-auto sm:p-2"
            aria-label="Filter by event"
            aria-expanded={filterPanelOpen}
          >
            <EventFilterIcon className="h-4 w-4 shrink-0" aria-hidden />
            {selectedCount > 0 && (
              <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full border border-gold bg-deepdark px-1 text-2xs font-semibold text-gold">
                {selectedCount}
              </span>
            )}
          </button>
        </div>
        <input
          type="search"
          value={searchValue}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={searchPlaceholder}
          className="min-w-0 flex-1 rounded border border-coffee bg-deepdark px-3 py-1.5 text-sm text-cream placeholder-taupe focus:outline-none focus:ring-1 focus:ring-gold sm:min-w-[8rem]"
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
      {showRefreshMetadata && (
        <div className="border-t border-soulsilver/40 px-4 py-2">
          <div className="flex flex-wrap items-center gap-3 text-2xs uppercase tracking-wide text-taupe">
            {refreshLabel !== "" && (
              <span className={refreshIsStale ? "text-error" : undefined}>
                <span className="font-mono text-cream">{refreshLabel}</span>
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
