"""Scrape a public Kodo People "Soft Skills PRO" report and dump it to JSON.

Two entry points:

    * scrape(url)                  – standalone (launches its own browser)
    * scrape_with_browser(browser) – reuses a browser owned by the caller (used
                                     by the FastAPI app to share a single
                                     Chromium across requests).

CLI usage:
    python scrape_kodo.py <report_url> [--out report.json] [--headful]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, Page, async_playwright


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


async def _extract_header(page: Page) -> dict[str, str | None]:
    return await page.evaluate(
        """
        () => {
          const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
          const items = {};
          document.querySelectorAll('.card__info__list ul li').forEach(li => {
            const label = norm(li.querySelector('span')?.textContent || '');
            const value = norm(li.textContent.replace(label, '').replace(/^[:\\s]+/, ''));
            if (label) {
              const key = label.toLowerCase().replace(/\\s+/g, '_');
              items[key] = value || null;
            }
          });
          const title = norm(document.querySelector('.card__title h2')?.textContent || '');
          return { ...items, assessment: title || null };
        }
        """
    )


async def _extract_radar_drivers(page: Page) -> list[dict[str, Any]]:
    return await page.evaluate(
        """
        () => {
          const el = document.getElementById('radar-chart');
          if (!el || !window.echarts) return [];
          const inst = echarts.getInstanceByDom(el);
          if (!inst) return [];
          const opt = inst.getOption();
          const radar = (opt.radar && opt.radar[0]) || {};
          const indicators = radar.indicator || [];
          const series = (opt.series && opt.series[0]) || {};
          const data = (series.data && series.data[0] && series.data[0].value) || [];
          return indicators.map((ind, i) => ({
            name: ind.name,
            max: ind.max ?? null,
            value: data[i] ?? null,
          }));
        }
        """
    )


async def _extract_driver_details(page: Page) -> list[dict[str, Any]]:
    return await page.evaluate(
        """
        () => {
          const num = (s) => {
            if (s == null) return null;
            const m = String(s).replace(/[^0-9eE+\\-.]/g, '');
            const n = parseFloat(m);
            return Number.isFinite(n) ? n : null;
          };
          const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
          const txt = (el) => clean(el?.textContent || '');

          const subs = [...document.querySelectorAll('.section-subtitle')];
          return subs.map((sub) => {
            const titleEl = sub.querySelector('.section-subtitle__text__title');
            const rawTitle = txt(titleEl);
            const m = rawTitle.match(/^(.*?):\\s*([\\-+\\d.,]+)\\s*$/);
            const name = m ? clean(m[1]) : rawTitle;
            const score = m ? num(m[2]) : null;

            let n = sub.nextElementSibling;
            let bodyEl = null, barsEl = null;
            while (n && !n.classList.contains('section-subtitle')) {
              if (!bodyEl && n.classList.contains('section-body')) bodyEl = n;
              if (!barsEl && n.classList.contains('section-bars')) barsEl = n;
              n = n.nextElementSibling;
            }

            const definition = (() => {
              const p = bodyEl?.querySelector('.section-body__paragraph');
              if (!p) return null;
              return txt(p).replace(/^Definition\\s*:\\s*/i, '');
            })();

            const variables = [...(barsEl?.querySelectorAll('.section-bars__bar') || [])].map((bar) => {
              const vname = txt(bar.querySelector('.section-bars__bar__title h4'));
              const below = txt(bar.querySelector('.section-bar__bar--below__text'));
              const above = txt(bar.querySelector('.section-bar__bar--above__text'));
              const markerEl = bar.querySelector('.marker[style*="left"]');
              const valueText = txt(markerEl?.querySelector('span'));
              const leftMatch = markerEl?.getAttribute('style')?.match(/left:\\s*([0-9.]+)%/);
              return {
                name: vname,
                value: num(valueText),
                marker_percent: leftMatch ? parseFloat(leftMatch[1]) : null,
                low_description: below || null,
                high_description: above || null,
              };
            });

            return { name, score, definition, variables };
          });
        }
        """
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def scrape_with_browser(browser: Browser, url: str, *, timeout_ms: int = 60_000) -> dict[str, Any]:
    """Scrape one URL reusing an existing Browser instance.

    A fresh BrowserContext is created per call so cookies/storage don't bleed
    between requests.
    """
    ctx = await browser.new_context(
        viewport={"width": 1440, "height": 2400},
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        locale="en-US",
    )
    try:
        page = await ctx.new_page()
        resp = await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        if not resp:
            raise RuntimeError("No response received from target URL")
        if resp.status >= 400:
            raise RuntimeError(f"Target returned HTTP {resp.status}")

        await page.wait_for_function(
            "() => window.echarts && echarts.getInstanceByDom(document.getElementById('radar-chart'))",
            timeout=15_000,
        )
        await page.wait_for_selector(".section-subtitle__text__title", timeout=15_000)

        header = await _extract_header(page)
        drivers = await _extract_radar_drivers(page)
        details = await _extract_driver_details(page)
    finally:
        await ctx.close()

    return {
        "source_url": url,
        "header": header,
        "behavioral_scoring": {
            "driver_count": len(drivers),
            "drivers": drivers,
        },
        "behavioral_variables_analysis": {
            "driver_count": len(details),
            "drivers": details,
        },
    }


async def scrape(url: str, *, headful: bool = False) -> dict[str, Any]:
    """Standalone scrape: spins up its own browser. Use for CLI / one-offs."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headful)
        try:
            return await scrape_with_browser(browser, url)
        finally:
            await browser.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape a Kodo People public report into JSON")
    ap.add_argument("url", help="Public report URL (the share link)")
    ap.add_argument("--out", default="report.json", help="Output JSON file (default: report.json)")
    ap.add_argument("--headful", action="store_true", help="Show the browser window")
    args = ap.parse_args()

    data = asyncio.run(scrape(args.url, headful=args.headful))
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Saved {args.out} — drivers in chart: {data['behavioral_scoring']['driver_count']}, "
        f"drivers in analysis: {data['behavioral_variables_analysis']['driver_count']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
