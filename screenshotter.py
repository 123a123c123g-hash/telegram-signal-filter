from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass

from playwright.async_api import async_playwright


URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PREFERRED_PARTS = ("crypto.netmotion.ru/shotdetectgraph",)


@dataclass(frozen=True)
class GraphScreenshotConfig:
    enabled: bool
    timeout_ms: int
    wait_ms: int
    viewport: tuple[int, int]
    full_page: bool
    cache_ttl_sec: int
    cleanup_max_age_sec: int
    cleanup_every: int
    max_parallel: int
    screenshots_dir: str


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def _parse_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _parse_viewport(value) -> tuple[int, int]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    if isinstance(value, str) and "x" in value:
        parts = value.lower().split("x", 1)
        try:
            return int(parts[0]), int(parts[1])
        except Exception:
            return 1280, 720
    return 1280, 720


def _get_cfg(cfg: dict, key: str, default):
    if key in cfg:
        return cfg.get(key)
    upper = key.upper()
    return cfg.get(upper, default)


def config_from_dict(cfg: dict, base_dir: str) -> GraphScreenshotConfig:
    enabled = _parse_bool(_get_cfg(cfg, "enable_graph_screenshot", True))
    timeout_ms = _parse_int(_get_cfg(cfg, "screenshot_timeout_ms", 15000), 15000)
    wait_ms = _parse_int(_get_cfg(cfg, "screenshot_wait_ms", 1500), 1500)
    viewport = _parse_viewport(_get_cfg(cfg, "screenshot_viewport", "1280x720"))
    full_page = _parse_bool(_get_cfg(cfg, "screenshot_full_page", True))
    screenshots_dir = os.path.join(base_dir, "screenshots")
    return GraphScreenshotConfig(
        enabled=enabled,
        timeout_ms=timeout_ms,
        wait_ms=wait_ms,
        viewport=viewport,
        full_page=full_page,
        cache_ttl_sec=600,
        cleanup_max_age_sec=86400,
        cleanup_every=20,
        max_parallel=2,
        screenshots_dir=screenshots_dir,
    )


def extract_graph_url(text: str) -> str | None:
    urls = URL_RE.findall(text or "")
    if not urls:
        return None
    for url in urls:
        lowered = url.lower()
        if any(part in lowered for part in PREFERRED_PARTS):
            return _strip_url(url)
    return _strip_url(urls[0])


def _strip_url(url: str) -> str:
    return url.rstrip(").,;\"'")


class GraphScreenshotter:
    def __init__(self, config: GraphScreenshotConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger
        self._cache: dict[str, tuple[float, str]] = {}
        self._counter = 0
        self._semaphore = None
        self._semaphore_by_exchange = {}
        self._playwright = None
        self._browsers = {}
        self._contexts = {}
        self._context_locks = {}
        os.makedirs(self._config.screenshots_dir, exist_ok=True)
        self._cleanup_old_files()

        def _get_semaphore(self, exchange_key: str | None = None):
        key = (exchange_key or "default").lower()
        if self._semaphore_by_exchange is None:
            self._semaphore_by_exchange = {}
        sem = self._semaphore_by_exchange.get(key)
        if sem is None:
            limit = max(1, int(self._config.max_parallel))
            sem = asyncio.Semaphore(limit)
            self._semaphore_by_exchange[key] = sem
        return sem

    async def _get_context(self, exchange_key: str | None = None):
        key = (exchange_key or "default").lower()
        lock = self._context_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._context_locks[key] = lock
        async with lock:
            ctx = self._contexts.get(key)
            if ctx is not None:
                try:
                    if not ctx.is_closed():
                        return ctx
                except Exception:
                    pass
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            browser = self._browsers.get(key)
            if browser is None or browser.is_closed():
                browser = await self._playwright.chromium.launch(headless=True)
                self._browsers[key] = browser
            ctx = await browser.new_context(
                viewport={"width": self._config.viewport[0], "height": self._config.viewport[1]}
            )
            self._contexts[key] = ctx
            self._logger.info("Screenshot context initialized: exchange=%s", key)
            return ctx
    async def take_screenshot(self, url: str) -> str | None:
        if not self._config.enabled:
            return None
        now = time.time()
        cached = self._cache.get(url)
        if cached and now - cached[0] <= self._config.cache_ttl_sec and os.path.exists(cached[1]):
            return cached[1]

        sem = self._get_semaphore((exchange or "").strip().lower())
        async with sem:
            now = time.time()
            cached = self._cache.get(url)
            if cached and now - cached[0] <= self._config.cache_ttl_sec and os.path.exists(cached[1]):
                return cached[1]
            try:
                path = await self._capture(url)
            except Exception as exc:
                self._logger.exception("Screenshot failed for %s: %s", url, exc)
                return None

            if path:
                self._cache[url] = (time.time(), path)
            self._counter += 1
            if self._counter % self._config.cleanup_every == 0:
                self._cleanup_old_files()
            return path

    async def _capture(self, url: str) -> str | None:
        filename = f"graph_{int(time.time())}_{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}.png"
        path = os.path.join(self._config.screenshots_dir, filename)
                context = await self._get_context(exchange_key)
        page = await context.new_page()
        await _goto_with_retry(
            page,
            url,
            wait_until_final,
            goto_timeout,
            self._logger,
            retry_on_network_change,
        )
        if force_reload:
            await _reload_with_retry(
                page,
                wait_until_final,
                goto_timeout,
                self._logger,
                retry_on_network_change,
            )
        wait_ms = self._config.wait_ms if force_wait_ms is None else max(0, int(force_wait_ms))
        await page.wait_for_timeout(wait_ms)
        if exchange_key == "bybit":
            ready_ok = await _wait_bybit_ready(
                page,
                self._config.bybit_ready_timeout_ms,
                self._config.bybit_after_ready_sleep_ms,
                self._config.bybit_blank_retry,
                self._config.bybit_blank_threshold,
                self._logger,
            )
            if not ready_ok:
                await page.close()
                return None
        if apply_delay and delay_sec > 0:
            self._logger.info(
                "Screenshot delay applied: exchange=%s delay=%.1fs", exchange_key, delay_sec
            )
            await page.wait_for_timeout(int(delay_sec * 1000))
        await page.screenshot(path=path, full_page=self._config.full_page)
        await page.close()
        return path

    def _cleanup_old_files(self) -> None:
        cutoff = time.time() - self._config.cleanup_max_age_sec
        for name in os.listdir(self._config.screenshots_dir):
            path = os.path.join(self._config.screenshots_dir, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except Exception:
                self._logger.exception("Failed to remove old screenshot %s", path)

