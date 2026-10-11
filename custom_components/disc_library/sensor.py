"""Disc sensor: the film in a disc player, from its fingerprint."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import DiscLibrary
from .const import CONF_PLAYERS, DISC_FORMATS, DOMAIN, MIN_FEATURE_SECONDS, TMDB_IMAGE

STATE_NO_DISC = "No disc"
STATE_DISC = "Disc"  # a disc is in but its main feature hasn't played yet
STATE_CHOOSE = "Choose"  # several films fit: name it once with disc_library.identify
STATE_UNKNOWN_DISC = "Unknown disc"  # not in the index and not named yet
MAX_CANDIDATES = 4
FORMAT_NAMES = {"uhd": "4K UHD", "bd": "Blu-ray", "dvd": "DVD"}


def _seconds(value: Any) -> int | None:
    """'02:10:14' -> 7814."""
    try:
        h, m, s = (int(x) for x in str(value).split(":"))
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


async def async_setup_platform(
    hass: HomeAssistant, config, async_add_entities: AddEntitiesCallback, discovery_info=None
) -> None:
    if discovery_info is None:
        return
    library: DiscLibrary = hass.data[DOMAIN]
    sensors = [DiscSensor(library, player) for player in discovery_info[CONF_PLAYERS]]
    async_add_entities(sensors)


class DiscSensor(SensorEntity):
    """Which film is in a disc player."""

    _attr_should_poll = False
    _attr_icon = "mdi:disc"

    def __init__(self, library: DiscLibrary, player: str) -> None:
        self._library = library
        self._player = player
        object_id = player.split(".", 1)[1]
        self._attr_unique_id = f"{DOMAIN}_{object_id}"
        self._attr_name = f"{object_id.replace('_', ' ').title()} Disc"
        self.entity_id = f"sensor.{object_id}_disc"
        self.fingerprint: str | None = None
        self._fmt: str | None = None
        self._disc_in = False

    async def async_added_to_hass(self) -> None:
        self.hass.data.setdefault(f"{DOMAIN}_sensors", {})[self.entity_id] = self
        self._library.listeners.append(self.async_write_ha_state)
        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._player], self._player_changed)
        )
        self._update_from(self.hass.states.get(self._player))

    async def async_will_remove_from_hass(self) -> None:
        self.hass.data.get(f"{DOMAIN}_sensors", {}).pop(self.entity_id, None)
        if self.async_write_ha_state in self._library.listeners:
            self._library.listeners.remove(self.async_write_ha_state)

    @callback
    def _player_changed(self, event: Event[EventStateChangedData]) -> None:
        if self._update_from(event.data["new_state"]):
            self.async_write_ha_state()

    def _update_from(self, state: State | None) -> bool:
        """Read the player; True if the disc or its fingerprint changed."""
        before = (self._disc_in, self.fingerprint)
        attrs = state.attributes if state else {}
        disc_type = str(attrs.get("disc_type") or "").strip().lower()
        fmt = DISC_FORMATS.get(disc_type)
        if not state or state.state in (STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN) or not fmt:
            # Off or no (video) disc: forget the fingerprint; the next disc starts afresh
            self._disc_in, self.fingerprint, self._fmt = False, None, None
            return before != (self._disc_in, self.fingerprint)
        if fmt != self._fmt:
            self.fingerprint = None
        self._disc_in, self._fmt = True, fmt
        # Only a feature-length title (not the menu loop, title 0) identifies the disc;
        # the fingerprint is kept while the menu or extras play afterwards
        seconds = _seconds(attrs.get("track_duration") or attrs.get("total_duration"))
        chapters = attrs.get("chapter_total")
        if (attrs.get("track") or 0) >= 1 and seconds and seconds >= MIN_FEATURE_SECONDS:
            self.fingerprint = f"{fmt}:{seconds}:{chapters}"
        return before != (self._disc_in, self.fingerprint)

    # ---------- result ----------
    def _result(self) -> tuple[dict | None, str | None, list[dict]]:
        """(film, how it was found, candidates)."""
        if not self.fingerprint:
            return None, None, []
        named = self._library.remembered.get(self.fingerprint)
        if named is not None:
            return self._library.film(named), "named", []
        fmt, seconds, chapters = self.fingerprint.split(":")
        candidates = self._library.candidates(
            fmt, int(seconds), int(chapters) if chapters.isdigit() else None)
        if candidates and candidates[0]["score"] <= 1 and (
            len(candidates) == 1 or candidates[1]["score"] >= candidates[0]["score"] + 2
        ):
            return candidates[0], "matched", []
        return None, None, candidates[:MAX_CANDIDATES]

    @property
    def native_value(self) -> str:
        if not self._disc_in:
            return STATE_NO_DISC
        if not self.fingerprint:
            return STATE_DISC
        film, _, candidates = self._result()
        if film:
            return film["t"]
        return STATE_CHOOSE if candidates else STATE_UNKNOWN_DISC

    @property
    def entity_picture(self) -> str | None:
        film, _, _ = self._result()
        if film and (film.get("b") or film.get("p")):
            return f"{TMDB_IMAGE}w1280{film.get('b') or film.get('p')}"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        film, found, candidates = self._result()
        attrs: dict[str, Any] = {
            "player": self._player,
            "fingerprint": self.fingerprint,
            "attribution": "Disc data: TheDiscDB; images: TMDB",
        }
        if film:
            attrs.update({
                "media_title": film["t"],
                "media_channel": " · ".join(
                    str(x) for x in (film.get("y"), FORMAT_NAMES.get(self._fmt or "")) if x),
                "tmdb_id": film["id"],
                "year": film.get("y"),
                "poster": f"{TMDB_IMAGE}w342{film['p']}" if film.get("p") else None,
                "found_by": found,
            })
        if candidates:
            attrs["candidates"] = [
                {"tmdb_id": c["id"], "title": c["t"], "year": c.get("y"),
                 "poster": f"{TMDB_IMAGE}w185{c['p']}" if c.get("p") else None}
                for c in candidates
            ]
        return attrs
