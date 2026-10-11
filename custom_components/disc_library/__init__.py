"""Disc Library: work out which film is in a disc player from the disc's fingerprint.

Players like the Oppo UDP-20x report the playing title's exact length and
chapter count but not the film's name. That fingerprint is matched against an
index built from TheDiscDB (see build_index.py); a disc whose match is
ambiguous, or that isn't catalogued, is named once with the `identify` action
and remembered from then on.

configuration.yaml (or a package):

    disc_library:
      players:
        - media_player.cinema_oppo
      # optional: where the index is kept, and where a newer one is fetched
      # from once a day ("" to never fetch)
      # index: disc_library/index.json
      # index_url: https://raw.githubusercontent.com/gadgetbazza/ha-disc-library/main/data/index.json
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path

import aiohttp

import voluptuous as vol

from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_INDEX,
    CONF_INDEX_URL,
    CONF_PLAYERS,
    DEFAULT_INDEX,
    DEFAULT_INDEX_URL,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_PLAYERS): cv.entity_ids,
                vol.Optional(CONF_INDEX, default=DEFAULT_INDEX): cv.string,
                vol.Optional(CONF_INDEX_URL, default=DEFAULT_INDEX_URL): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

SERVICE_IDENTIFY = "identify"
SERVICE_FORGET = "forget"
ATTR_TMDB_ID = "tmdb_id"
UPDATE_INTERVAL = timedelta(hours=24)


class DiscLibrary:
    """The film index and the discs named so far (fingerprint -> TMDB id)."""

    def __init__(self, hass: HomeAssistant, index_path: str) -> None:
        self.hass = hass
        self._index_path = Path(hass.config.path(index_path))
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.entries: list[dict] = []
        self.films: dict[int, dict] = {}
        self.remembered: dict[str, int] = {}
        self.listeners: list = []

    async def async_load(self) -> None:
        def _read() -> list[dict]:
            if not self._index_path.exists():
                _LOGGER.warning("No disc index at %s; only named discs will be recognised",
                                self._index_path)
                return []
            return json.loads(self._index_path.read_text())["entries"]

        self._set_entries(await self.hass.async_add_executor_job(_read))
        self.remembered = (await self._store.async_load() or {}).get("discs", {})
        _LOGGER.debug("Loaded %d indexed features, %d named discs",
                      len(self.entries), len(self.remembered))

    def _set_entries(self, entries: list[dict]) -> None:
        self.entries = entries
        self.films = {e["id"]: e for e in entries}

    async def async_update_index(self, url: str) -> None:
        """Fetch the published index and switch to it if it changed."""
        try:
            async with async_get_clientsession(self.hass).get(
                url, timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                resp.raise_for_status()
                raw = await resp.text()
            entries = json.loads(raw)["entries"]
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError) as err:
            _LOGGER.warning("Could not fetch the disc index from %s: %s", url, err)
            return
        if not entries or entries == self.entries:
            return

        def _write() -> None:
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._index_path.with_suffix(".tmp")
            tmp.write_text(raw)
            tmp.replace(self._index_path)

        await self.hass.async_add_executor_job(_write)
        added = len(entries) - len(self.entries)
        self._set_entries(entries)
        _LOGGER.info("Disc index updated: %d features (%+d)", len(entries), added)
        for listener in self.listeners:
            listener()

    def film(self, tmdb_id: int) -> dict | None:
        """A film in the index by TMDB id (a named disc keeps showing it)."""
        return self.films.get(tmdb_id)

    def candidates(self, fmt: str, seconds: int, chapters: int | None) -> list[dict]:
        """Films whose main feature runs within 3 s, best first, one per film.

        Format (UHD/Blu-ray/DVD) is preferred, not required: the same cut is
        usually identical across a film's releases.
        """
        scored = []
        for e in self.entries:
            diff = abs(e["d"] - seconds)
            if diff > 3:
                continue
            chap = abs((e["c"] or 0) - chapters) if chapters is not None and e["c"] else 2
            scored.append((diff + min(chap, 2) + (0 if e["f"] == fmt else 1), e))
        best: dict[int, tuple] = {}
        # score = seconds off + chapters off (max 2) + 1 for another format;
        # above 4 the fit is too poor to suggest
        for score, e in sorted((x for x in scored if x[0] <= 4), key=lambda x: x[0]):
            best.setdefault(e["id"], (score, e))
        return [dict(e, score=s) for s, e in sorted(best.values(), key=lambda x: x[0])]

    async def async_remember(self, fingerprint: str, tmdb_id: int | None) -> None:
        if tmdb_id is None:
            self.remembered.pop(fingerprint, None)
        else:
            self.remembered[fingerprint] = tmdb_id
        await self._store.async_save({"discs": self.remembered})
        for listener in self.listeners:
            listener()


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config.get(DOMAIN)
    if conf is None:
        return True
    library = DiscLibrary(hass, conf[CONF_INDEX])
    await library.async_load()
    hass.data[DOMAIN] = library

    def _sensor(entity_id: str):
        sensors = hass.data.get(f"{DOMAIN}_sensors", {})
        return sensors.get(entity_id)

    async def identify(call: ServiceCall) -> None:
        """Name the disc now in the player (the sensor targeted) as a TMDB film."""
        for entity_id in call.data[ATTR_ENTITY_ID]:
            sensor = _sensor(entity_id)
            if sensor and sensor.fingerprint:
                await library.async_remember(sensor.fingerprint, call.data[ATTR_TMDB_ID])

    async def forget(call: ServiceCall) -> None:
        """Forget the name given to the disc now in the player."""
        for entity_id in call.data[ATTR_ENTITY_ID]:
            sensor = _sensor(entity_id)
            if sensor and sensor.fingerprint:
                await library.async_remember(sensor.fingerprint, None)

    hass.services.async_register(
        DOMAIN, SERVICE_IDENTIFY, identify,
        schema=vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
                           vol.Required(ATTR_TMDB_ID): vol.Coerce(int)}))
    hass.services.async_register(
        DOMAIN, SERVICE_FORGET, forget,
        schema=vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_ids}))

    if url := conf[CONF_INDEX_URL]:
        async def _update(_now=None) -> None:
            await library.async_update_index(url)

        # once shortly after start-up, then daily
        async_call_later(hass, 60, _update)
        async_track_time_interval(hass, _update, UPDATE_INTERVAL)

    hass.async_create_task(
        discovery.async_load_platform(hass, Platform.SENSOR, DOMAIN, {CONF_PLAYERS: conf[CONF_PLAYERS]}, config)
    )
    return True
