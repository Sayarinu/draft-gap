"use client";

interface EventFilterPanelProps {
  isOpen: boolean;
  onClose: () => void;
  eventOptions: string[];
  selectedEvents: Set<string>;
  onToggleEvent: (eventName: string) => void;
  onClearAll: () => void;
}

export const EventFilterPanel = ({
  isOpen,
  onClose,
  eventOptions,
  selectedEvents,
  onToggleEvent,
  onClearAll,
}: EventFilterPanelProps) => {
  if (!isOpen) return null;

  return (
    <div
      className="absolute left-0 top-full z-50 mt-1 w-72 rounded-lg border border-coffee bg-deepdark p-4 shadow-lg"
      role="dialog"
      aria-label="Filter by event"
    >
        <div className="mb-3 flex items-center justify-between border-b border-coffee pb-2">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-gold">
            Filter by event
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="text-taupe hover:text-cream focus:outline-none focus:ring-2 focus:ring-gold focus:ring-offset-2 focus:ring-offset-deepdark rounded px-1"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <div className="max-h-64 overflow-y-auto space-y-1">
          {eventOptions.map((name) => (
            <label
              key={name}
              className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-concrete/50"
            >
              <input
                type="checkbox"
                checked={selectedEvents.has(name)}
                onChange={() => onToggleEvent(name)}
                className="h-4 w-4 rounded border-coffee bg-concrete text-gold focus:ring-gold"
              />
              <span className="text-sm text-cream">{name}</span>
            </label>
          ))}
        </div>
        <div className="mt-3 flex gap-2 border-t border-coffee pt-3">
          <button
            type="button"
            onClick={onClearAll}
            className="rounded border border-coffee px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-taupe hover:bg-coffee/30 focus:outline-none focus:ring-2 focus:ring-gold focus:ring-offset-2 focus:ring-offset-deepdark"
          >
            Clear
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded bg-gold px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-deepdark hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-gold focus:ring-offset-2 focus:ring-offset-deepdark"
          >
            Done
          </button>
        </div>
      </div>
  );
};
