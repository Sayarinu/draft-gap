"use client";

import { useEffect, useState } from "react";
import type { SyntheticEvent } from "react";

interface LiveStreamPanelProps {
  matchLabel: string;
  streamUrl: string;
}

const EMBED_TIMEOUT_MS = 8000;

export const LiveStreamPanel = ({ matchLabel, streamUrl }: LiveStreamPanelProps) => {
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");

  const handleLoad = (event: SyntheticEvent<HTMLIFrameElement>) => {
    try {
      const loadedHref = event.currentTarget.contentWindow?.location.href;
      if (!loadedHref || loadedHref === "about:blank") {
        return;
      }
      setStatus("ready");
    } catch {
      setStatus("ready");
    }
  };

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setStatus((current) => (current === "loading" ? "failed" : current));
    }, EMBED_TIMEOUT_MS);

    return () => window.clearTimeout(timeoutId);
  }, [streamUrl]);

  return (
    <div className="rounded-xl border border-coffee bg-deepdark/70 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.24em] text-gold">
            Live stream
          </p>
          <p className="mt-1 text-sm text-cream">{matchLabel}</p>
        </div>
        <a
          href={streamUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded border border-gold/60 bg-gold/10 px-3 py-2 text-2xs font-semibold uppercase tracking-[0.22em] text-gold transition-colors hover:bg-gold/20 focus:outline-none focus:ring-2 focus:ring-gold focus:ring-offset-2 focus:ring-offset-deepdark"
        >
          Open in new tab
        </a>
      </div>
      {status === "failed" ? (
        <div className="flex min-h-56 flex-col items-center justify-center rounded-lg border border-dashed border-coffee bg-deepdark px-6 py-8 text-center">
          <p className="text-sm font-medium text-cream">
            This stream could not be embedded in the app.
          </p>
          <p className="mt-2 max-w-xl text-xs leading-5 text-taupe">
            Some providers block iframe playback. Use the button above to open the stream in a new tab.
          </p>
        </div>
      ) : (
        <div className="relative overflow-hidden rounded-lg border border-coffee bg-black">
          {status === "loading" && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-deepdark/85">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-gold">
                Loading stream...
              </p>
            </div>
          )}
          <div className="aspect-video w-full">
            <iframe
              key={streamUrl}
              src={streamUrl}
              title={`${matchLabel} stream`}
              allow="autoplay; fullscreen; picture-in-picture"
              allowFullScreen
              className="h-full w-full border-0"
              onLoad={handleLoad}
            />
          </div>
        </div>
      )}
    </div>
  );
};
