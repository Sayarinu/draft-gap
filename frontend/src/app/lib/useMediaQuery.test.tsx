import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useMediaQuery } from "./useMediaQuery";

interface MatchMediaMockOptions {
  useLegacyListeners?: boolean;
}

const setupMatchMedia = ({ useLegacyListeners = false }: MatchMediaMockOptions = {}) => {
  const addEventListener = vi.fn();
  const removeEventListener = vi.fn();
  const addListener = vi.fn();
  const removeListener = vi.fn();

  const matchMedia = vi.fn().mockImplementation(() => ({
    matches: true,
    media: "(max-width: 767px)",
    onchange: null,
    addEventListener: useLegacyListeners ? undefined : addEventListener,
    removeEventListener: useLegacyListeners ? undefined : removeEventListener,
    addListener: useLegacyListeners ? addListener : undefined,
    removeListener: useLegacyListeners ? removeListener : undefined,
    dispatchEvent: vi.fn(),
  }));

  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: matchMedia,
  });

  return {
    addEventListener,
    removeEventListener,
    addListener,
    removeListener,
  };
};

describe("useMediaQuery", () => {
  const originalMatchMedia = window.matchMedia;

  afterEach(() => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: originalMatchMedia,
    });
  });

  it("uses modern media query listeners when available", () => {
    const listeners = setupMatchMedia();

    const { result, unmount } = renderHook(() => useMediaQuery("(max-width: 767px)"));

    expect(result.current).toBe(true);
    expect(listeners.addEventListener).toHaveBeenCalledWith("change", expect.any(Function));

    unmount();

    expect(listeners.removeEventListener).toHaveBeenCalledWith("change", expect.any(Function));
  });

  it("falls back to legacy listeners on mobile-compatible browsers", () => {
    const listeners = setupMatchMedia({ useLegacyListeners: true });

    const { result, unmount } = renderHook(() => useMediaQuery("(max-width: 767px)"));

    expect(result.current).toBe(true);
    expect(listeners.addListener).toHaveBeenCalledWith(expect.any(Function));

    unmount();

    expect(listeners.removeListener).toHaveBeenCalledWith(expect.any(Function));
  });
});
