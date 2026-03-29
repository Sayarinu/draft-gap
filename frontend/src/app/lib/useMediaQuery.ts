import { useSyncExternalStore } from "react";

interface LegacyMediaQueryList extends MediaQueryList {
  addListener?: (listener: (event: MediaQueryListEvent) => void) => void;
  removeListener?: (listener: (event: MediaQueryListEvent) => void) => void;
}

function getMediaQueryList(query: string): LegacyMediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return null;
  }
  return window.matchMedia(query) as LegacyMediaQueryList;
}

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onStoreChange) => {
      const media = getMediaQueryList(query);
      if (!media) {
        return () => undefined;
      }

      const listener = () => onStoreChange();
      if (typeof media.addEventListener === "function") {
        media.addEventListener("change", listener);
        return () => media.removeEventListener("change", listener);
      }

      if (typeof media.addListener === "function") {
        media.addListener(listener);
        return () => media.removeListener?.(listener);
      }

      return () => undefined;
    },
    () => getMediaQueryList(query)?.matches ?? false,
    () => false,
  );
}

export function useIsMobile(): boolean {
  return useMediaQuery("(max-width: 767px)");
}
