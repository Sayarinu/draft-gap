import { beforeEach, describe, expect, it, vi } from "vitest";

import { getApiBaseUrl } from "./api";

describe("getApiBaseUrl", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.stubEnv("VITE_API_URL", "");
  });

  it("uses localhost backend by default in local development", () => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: new URL("http://localhost:3000"),
    });

    expect(getApiBaseUrl()).toBe("http://localhost:8000");
  });

  it("uses same-origin requests in production when no override is set", () => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: new URL("https://draft-gap.sayarin.xyz"),
    });

    expect(getApiBaseUrl()).toBe("");
  });

  it("honors an explicit API URL override", () => {
    vi.stubEnv("VITE_API_URL", "https://api.example.com/");
    Object.defineProperty(window, "location", {
      configurable: true,
      value: new URL("https://draft-gap.sayarin.xyz"),
    });

    expect(getApiBaseUrl()).toBe("https://api.example.com");
  });
});
