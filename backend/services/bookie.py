from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlparse

THUNDERPICK_LOL_URL = "https://thunderpick.io/esports/league-of-legends"
ODDS_CACHE_FILENAME = "thunderpick_odds.json"
DEFAULT_TIMEOUT_MS = 45_000
WAIT_AFTER_LOAD_MS = 12_000

BELGIUM_LOCALE = "en-BE"
BELGIUM_TIMEZONE = "Europe/Brussels"
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

MAX_ATTEMPTS = 3
RETRY_DELAY_RANGE = (30, 45)
MAX_EXTRACTED_MATCHES = 80

logger = logging.getLogger(__name__)


class BookieMatchOdds(TypedDict):
    team1: str
    team2: str
    odds1: float
    odds2: float


def get_odds_cache_dir() -> Path:
    return Path(os.getenv("PANDASCORE_OUTPUT_DIR", "/cache/pandascore"))


def get_odds_cache_path(output_dir: str | Path | None = None) -> Path:
    return Path(output_dir or get_odds_cache_dir()) / ODDS_CACHE_FILENAME


def read_odds_from_file(
    output_dir: str | Path | None = None,
) -> list[BookieMatchOdds]:
    path = get_odds_cache_path(output_dir)
    if not path.is_file():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [
            {
                "team1": str(m.get("team1", "")).strip(),
                "team2": str(m.get("team2", "")).strip(),
                "odds1": float(m.get("odds1", 0)),
                "odds2": float(m.get("odds2", 0)),
            }
            for m in data
            if m.get("team1") and m.get("team2") and m.get("odds1") and m.get("odds2")
        ]
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return []


def _write_odds_cache(results: list[BookieMatchOdds], cache_path: Path) -> None:
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(
                [{"team1": r["team1"], "team2": r["team2"], "odds1": r["odds1"], "odds2": r["odds2"]} for r in results],
                f,
                indent=2,
            )
        logger.info("Betting odds scraper: wrote %d matches to %s", len(results), cache_path)
    except OSError as e:
        logger.warning("Betting odds scraper: failed to write cache: %s", e)


def _write_debug_snippet(body_text: str, cache_dir: Path) -> None:
    try:
        snippet_path = cache_dir / "thunderpick_page_snippet.txt"
        with open(snippet_path, "w", encoding="utf-8") as f:
            f.write(body_text[:12000] if body_text else "(Page body was empty or could not be retrieved)\n")
        logger.info("Betting odds scraper: saved page snippet to %s", snippet_path)
    except OSError as e:
        logger.warning("Betting odds scraper: could not write snippet: %s", e)


def _normalize_team_name(name: str) -> str:
    s = (name or "").lower().strip()
    for suffix in (" esports", " esport", " lol", " league of legends"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    s = " ".join(s.replace(".", " ").split())
    return s


def _name_matches(a: str, b: str, acr_a: str | None) -> bool:
    na = _normalize_team_name(a)
    nb = _normalize_team_name(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    if acr_a:
        acr = acr_a.lower().strip()
        if acr and (acr == nb or acr in nb or nb in acr):
            return True
    return False


def find_odds_for_match(
    team1: str,
    team2: str,
    odds_list: list[BookieMatchOdds],
    acronym1: str | None = None,
    acronym2: str | None = None,
) -> tuple[float | None, float | None]:
    n1 = _normalize_team_name(team1)
    n2 = _normalize_team_name(team2)
    if not n1 or not n2:
        return (None, None)
    for row in odds_list:
        if not (_normalize_team_name(row["team1"]) and _normalize_team_name(row["team2"])):
            continue
        if _name_matches(team1, row["team1"], acronym1) and _name_matches(team2, row["team2"], acronym2):
            return (row["odds1"], row["odds2"])
        if _name_matches(team1, row["team2"], acronym1) and _name_matches(team2, row["team1"], acronym2):
            return (row["odds2"], row["odds1"])
    return (None, None)


def _extract_lol_section(text: str) -> str:
    for marker in ("League of Legends Betting Odds", "What is League of Legends", "What is LoL"):
        idx = text.find(marker)
        if idx > 500:
            return text[:idx]
    return text


_SKIP_RE = re.compile(r"\b(\d{4}|Playoffs|Cup|League|Season|Split|Masters|Challengers|Qualifier)\b", re.I)
_SKIP_NAMES_RE = re.compile(r"^(LIVE|BO\d|Featured|\d+:\d+)$")


def _extract_from_page_text(text: str) -> list[BookieMatchOdds]:
    text = _extract_lol_section(text)
    results: list[BookieMatchOdds] = []
    seen: set[tuple[str, str, float, float]] = set()
    decimal_re = re.compile(r"\d+\.\d{1,2}")

    vs_pattern = re.compile(
        r"([A-Za-z0-9.][A-Za-z0-9.\s]{1,28}?)\s+(\d+\.\d{1,2})\s+vs\s+([A-Za-z0-9.][A-Za-z0-9.\s]{1,28}?)\s+(\d+\.\d{1,2})",
        re.IGNORECASE,
    )
    for m in vs_pattern.finditer(text):
        t1_raw = m.group(1).strip()
        t2_raw = m.group(3).strip()
        t1 = t1_raw.split("\n")[-1].strip() if "\n" in t1_raw else t1_raw
        t2 = t2_raw.split("\n")[0].strip() if "\n" in t2_raw else t2_raw
        o1 = float(m.group(2))
        o2 = float(m.group(4))
        if not (1.01 <= o1 <= 50 and 1.01 <= o2 <= 50):
            continue
        if len(t1) < 2 or len(t2) < 2:
            continue
        if _SKIP_NAMES_RE.match(t1) or _SKIP_NAMES_RE.match(t2):
            continue
        if _SKIP_RE.search(t1) or _SKIP_RE.search(t2):
            continue
        key = (t1.lower(), t2.lower(), min(o1, o2), max(o1, o2))
        if key not in seen:
            seen.add(key)
            results.append(BookieMatchOdds(team1=t1, team2=t2, odds1=o1, odds2=o2))

    if not results:
        for vs_m in re.finditer(r"\bvs\b", text):
            start = max(0, vs_m.start() - 120)
            end = min(len(text), vs_m.end() + 120)
            window = text[start:end]
            decimals = decimal_re.findall(window)
            if len(decimals) >= 2:
                o1, o2 = float(decimals[0]), float(decimals[1])
                if not (1.01 <= o1 <= 50 and 1.01 <= o2 <= 50):
                    continue
                parts = re.split(r"[\s\n]+", window)
                team_candidates = [
                    p.strip()
                    for p in parts
                    if 2 <= len(p.strip()) <= 28
                    and p not in (decimals[0], decimals[1])
                    and not re.match(r"^\d+\.\d{1,2}$", p)
                    and re.search(r"[a-zA-Z]", p)
                ]
                if len(team_candidates) >= 2:
                    t1, t2 = team_candidates[0], team_candidates[-1]
                    key = (t1.lower(), t2.lower(), min(o1, o2), max(o1, o2))
                    if key not in seen:
                        seen.add(key)
                        results.append(BookieMatchOdds(team1=t1, team2=t2, odds1=o1, odds2=o2))

    if not results:
        odds_first = re.compile(
            r"(\d+\.\d{1,2})\s+([A-Za-z0-9.][A-Za-z0-9.\s]{1,28}?)\s+vs\s+(\d+\.\d{1,2})\s+([A-Za-z0-9.][A-Za-z0-9.\s]{1,28}?)",
            re.IGNORECASE,
        )
        for m in odds_first.finditer(text):
            o1, o2 = float(m.group(1)), float(m.group(3))
            if not (1.01 <= o1 <= 50 and 1.01 <= o2 <= 50):
                continue
            t1 = m.group(2).strip().split("\n")[-1].strip() if "\n" in m.group(2) else m.group(2).strip()
            t2 = m.group(4).strip().split("\n")[0].strip() if "\n" in m.group(4) else m.group(4).strip()
            if len(t1) < 2 or len(t2) < 2:
                continue
            if _SKIP_NAMES_RE.match(t1) or _SKIP_NAMES_RE.match(t2):
                continue
            if _SKIP_RE.search(t1) or _SKIP_RE.search(t2):
                continue
            key = (t1.lower(), t2.lower(), min(o1, o2), max(o1, o2))
            if key not in seen:
                seen.add(key)
                results.append(BookieMatchOdds(team1=t1, team2=t2, odds1=o1, odds2=o2))

    return results[:MAX_EXTRACTED_MATCHES]


def _merge_extracted_results(
    dom_results: list[BookieMatchOdds],
    text_results: list[BookieMatchOdds],
) -> list[BookieMatchOdds]:
    merged: list[BookieMatchOdds] = []
    seen: set[tuple[str, str]] = set()
    for row in text_results + dom_results:
        team1 = str(row.get("team1", "")).strip()
        team2 = str(row.get("team2", "")).strip()
        odds1 = float(row.get("odds1", 0.0))
        odds2 = float(row.get("odds2", 0.0))
        if not team1 or not team2:
            continue
        if not (1.01 <= odds1 <= 50 and 1.01 <= odds2 <= 50):
            continue
        n1 = _normalize_team_name(team1)
        n2 = _normalize_team_name(team2)
        if not n1 or not n2:
            continue
        key = tuple(sorted((n1, n2)))
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            BookieMatchOdds(
                team1=team1,
                team2=team2,
                odds1=odds1,
                odds2=odds2,
            )
        )
        if len(merged) >= MAX_EXTRACTED_MATCHES:
            break
    return merged


def _is_blocked(body_text: str) -> bool:
    lower = body_text.lower()
    return "you have been blocked" in lower or "something went wrong" in lower or len(body_text) < 200


def _parse_proxy_env() -> dict[str, str] | None:
    raw = os.getenv("BOOKIE_HTTP_PROXY", "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    server = f"{parsed.scheme or 'http'}://{parsed.hostname}:{parsed.port}"
    proxy: dict[str, str] = {"server": server}
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return proxy


def _run_playwright_attempt(
    timeout_ms: int,
    proxy: dict[str, str] | None,
    cache_dir: Path,
) -> tuple[list[BookieMatchOdds], str]:
    from playwright.sync_api import sync_playwright

    results: list[BookieMatchOdds] = []
    body_text = ""

    chrome_channel = os.getenv("BOOKIE_USE_CHROME", "").strip().lower() in {"1", "true", "yes"}

    with sync_playwright() as p:
        launch_kwargs: dict[str, object] = {
            "headless": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--lang=en-BE",
            ],
        }
        if chrome_channel:
            launch_kwargs["channel"] = "chrome"

        try:
            browser = p.chromium.launch(**launch_kwargs)  # type: ignore[arg-type]
        except Exception as e:
            logger.warning("Betting odds scraper: Chromium launch failed: %s", e)
            return results, body_text

        try:
            context_kwargs: dict[str, object] = {
                "user_agent": CHROME_USER_AGENT,
                "viewport": {"width": 1920, "height": 1080},
                "locale": BELGIUM_LOCALE,
                "timezone_id": BELGIUM_TIMEZONE,
                "java_script_enabled": True,
                "ignore_https_errors": False,
                "extra_http_headers": {
                    "Accept-Language": "en-BE,en;q=0.9,nl;q=0.8",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Sec-CH-UA": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
                    "Sec-CH-UA-Mobile": "?0",
                    "Sec-CH-UA-Platform": '"Windows"',
                    "Upgrade-Insecure-Requests": "1",
                },
            }
            if proxy:
                context_kwargs["proxy"] = proxy
                logger.info(
                    "Betting odds scraper: using proxy server=%s",
                    proxy.get("server", "unknown"),
                )

            context = browser.new_context(**context_kwargs)  # type: ignore[arg-type]
            context.grant_permissions(["geolocation"])
            page = context.new_page()

            try:
                from playwright_stealth import stealth_sync
                stealth_sync(page)
            except ImportError:
                pass

            pre_delay = random.uniform(1.0, 3.0)
            logger.debug("Betting odds scraper: pre-navigation delay %.1fs", pre_delay)
            time.sleep(pre_delay)

            page.goto(
                THUNDERPICK_LOL_URL,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            page.wait_for_timeout(int(random.uniform(500, 1500)))
            page.wait_for_timeout(WAIT_AFTER_LOAD_MS)

            try:
                page.wait_for_function(
                    "() => document.body && /\\d+\\.\\d{2}/.test(document.body.innerText)",
                    timeout=15_000,
                )
            except Exception:
                pass

            page.evaluate(
                """
                () => {
                    for (let i = 0; i < 6; i += 1) {
                        window.scrollBy(0, Math.max(600, Math.floor(window.innerHeight * 0.9)));
                    }
                }
                """
            )
            page.wait_for_timeout(2_500)

        except Exception as e:
            logger.warning("Betting odds scraper: page load failed: %s", e)
            try:
                body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
                body_text = body_text if isinstance(body_text, str) else ""
                logger.warning(
                    "Betting odds scraper: page content on load failure (first 300): %s",
                    (body_text or "(empty)")[:300].replace("\n", " "),
                )
            except Exception:
                pass
            browser.close()
            return results, body_text

        try:
            screenshot_path = str(cache_dir / "thunderpick_debug.png")
            page.screenshot(path=screenshot_path, full_page=False)
            logger.info("Betting odds scraper: saved debug screenshot to %s", screenshot_path)
        except Exception as e:
            logger.debug("Betting odds scraper: screenshot failed: %s", e)

        dom_results: list[BookieMatchOdds] = []
        try:
            scraped = page.evaluate(
                """
                () => {
                    const oddsRegex = /^\\d+\\.\\d{1,2}$/;
                    const blockedTokenRegex = /^(live|bo\\d|vs|featured|today|tomorrow|map\\d+)$/i;
                    const rows = [];
                    const seen = new Set();
                    const all = document.querySelectorAll('[data-testid*="match"], [class*="match"], article, a[href*="esports"], [role="listitem"], div, span, p');
                    for (const el of all) {
                        const text = (el.textContent || '').trim();
                        if (text.length < 12 || text.length > 700) continue;
                        const parts = text.split(/\\s+/).filter(Boolean);
                        const numbers = parts.filter(p => oddsRegex.test(p)).map(Number);
                        const possibleOdds = numbers.filter(n => n >= 1.01 && n <= 50);
                        if (possibleOdds.length >= 2) {
                            const teamLike = parts.filter((p) => {
                                if (oddsRegex.test(p) || !isNaN(Number(p))) return false;
                                const normalized = p.replace(/[.,]/g, '').trim().toLowerCase();
                                if (!normalized || normalized.length < 3 || normalized.length > 30) return false;
                                if (blockedTokenRegex.test(normalized)) return false;
                                return /[a-z]/i.test(normalized);
                            });
                            const teams = teamLike.slice(0, 2);
                            if (teams.length >= 2) {
                                const key = teams.slice().sort().join('|') + '|' + possibleOdds.slice(0, 2).sort((a,b)=>a-b).join('|');
                                if (!seen.has(key)) {
                                    seen.add(key);
                                    rows.push({ team1: teams[0], team2: teams[1], odds1: possibleOdds[0], odds2: possibleOdds[1] });
                                }
                            }
                        }
                    }
                    return rows.slice(0, 80);
                }
                """
            )
            if isinstance(scraped, list) and scraped:
                for r in scraped:
                    if (
                        isinstance(r, dict)
                        and r.get("team1") and r.get("team2")
                        and isinstance(r.get("odds1"), (int, float))
                        and isinstance(r.get("odds2"), (int, float))
                    ):
                        dom_results.append(BookieMatchOdds(
                            team1=str(r["team1"]).strip(),
                            team2=str(r["team2"]).strip(),
                            odds1=float(r["odds1"]),
                            odds2=float(r["odds2"]),
                        ))
                logger.info("Betting odds scraper: DOM extraction found %d matches", len(dom_results))
        except Exception as e:
            logger.warning("Betting odds scraper: DOM evaluate failed: %s", e)

        try:
            body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
            body_text = body_text if isinstance(body_text, str) else ""
        except Exception as e:
            logger.warning("Betting odds scraper: could not get body text: %s", e)

        text_results: list[BookieMatchOdds] = []
        if len(body_text) > 500:
            text_results = _extract_from_page_text(body_text)
            if text_results:
                logger.info("Betting odds scraper: text extraction found %d matches", len(text_results))
            elif not dom_results:
                logger.info("Betting odds scraper: text extraction found 0 matches")
        results = _merge_extracted_results(dom_results, text_results)
        if results:
            sample_pairs = ", ".join(f"{row['team1']} vs {row['team2']}" for row in results[:5])
            logger.info(
                "Betting odds scraper: merged extraction found %d matches (dom=%d text=%d) sample=%s",
                len(results),
                len(dom_results),
                len(text_results),
                sample_pairs or "(none)",
            )

        context.close()
        browser.close()

    return results, body_text


def _scrape_via_playwright(
    cache_dir: Path,
    cache_path: Path,
    timeout_ms: int,
) -> list[BookieMatchOdds]:
    try:
        from playwright.sync_api import sync_playwright as _  # noqa: F401
    except ImportError as e:
        logger.warning("Betting odds scraper: Playwright not available: %s", e)
        return []

    proxy = _parse_proxy_env()
    if proxy:
        logger.info("Betting odds scraper: proxy configured")
    else:
        logger.info(
            "Betting odds scraper: no BOOKIE_HTTP_PROXY set — traffic uses Docker host IP. "
            "Set BOOKIE_HTTP_PROXY (e.g. http://host.docker.internal:8888) to use host VPN."
        )

    results: list[BookieMatchOdds] = []
    body_text = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info("Betting odds scraper: Playwright attempt %d/%d", attempt, MAX_ATTEMPTS)
        results, body_text = _run_playwright_attempt(timeout_ms, proxy, cache_dir)

        if results:
            break

        if attempt < MAX_ATTEMPTS:
            if _is_blocked(body_text):
                delay = random.uniform(*RETRY_DELAY_RANGE)
                logger.warning(
                    "Betting odds scraper: blocked on attempt %d — retrying in %.0fs",
                    attempt,
                    delay,
                )
                time.sleep(delay)
            else:
                logger.warning("Betting odds scraper: 0 matches on attempt %d — retrying", attempt)
                time.sleep(5)

    if not results:
        _log_blocked(body_text)
        _write_debug_snippet(body_text, cache_dir)

    return results


def _log_blocked(body_text: str) -> None:
    body_lower = (body_text or "").lower()
    if "you have been blocked" in body_lower:
        logger.warning(
            "Betting odds scraper: request was blocked (Cloudflare). "
            "Set BOOKIE_HTTP_PROXY to route through your host VPN (see docs/bookie-scraper.md)."
        )
    elif "something went wrong" in body_lower:
        logger.warning(
            "Betting odds scraper: page returned 'Something went wrong'. "
            "Check thunderpick_page_snippet.txt in the cache volume."
        )
    preview = (body_text or "(empty)")[:400].replace("\n", " ")
    logger.info(
        "Betting odds scraper: no matches extracted. Page preview: %s...",
        preview,
    )


def scrape_lol_odds(
    output_dir: str | Path | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> list[BookieMatchOdds]:
    cache_dir = Path(output_dir or get_odds_cache_dir())
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / ODDS_CACHE_FILENAME

    results = _scrape_via_playwright(cache_dir, cache_path, timeout_ms)

    if results:
        _write_odds_cache(results, cache_path)
    else:
        logger.warning("Betting odds scraper: all attempts exhausted — no matches extracted")

    return results
