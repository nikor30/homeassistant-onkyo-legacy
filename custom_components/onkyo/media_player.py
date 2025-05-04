"""Support for Onkyo Receivers."""

from __future__ import annotations

import logging
import socket
from typing import Any

import eiscp
from eiscp import eISCP
import voluptuous as vol

from homeassistant.components.media_player import (
    DOMAIN,
    PLATFORM_SCHEMA,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.const import ATTR_ENTITY_ID, CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

_LOGGER = logging.getLogger(__name__)

CONF_SOURCES = "sources"
CONF_MAX_VOLUME = "max_volume"
CONF_RECEIVER_MAX_VOLUME = "receiver_max_volume"

DEFAULT_NAME = "Onkyo Receiver"
SUPPORTED_MAX_VOLUME = 100
DEFAULT_RECEIVER_MAX_VOLUME = 80

SUPPORT_ONKYO_WO_VOLUME = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PLAY_MEDIA
)
SUPPORT_ONKYO = (
    SUPPORT_ONKYO_WO_VOLUME
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_STEP
)

KNOWN_HOSTS: list[str] = []
DEFAULT_SOURCES = {
    "tv": "TV",
    "bd": "Bluray",
    "game": "Game",
    "aux1": "Aux1",
    "video1": "Video 1",
    "video2": "Video 2",
    "video3": "Video 3",
    "video4": "Video 4",
    "video5": "Video 5",
    "video6": "Video 6",
    "video7": "Video 7",
    "fm": "Radio",
}
DEFAULT_PLAYABLE_SOURCES = ("fm", "am", "tuner")

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_HOST): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_MAX_VOLUME, default=SUPPORTED_MAX_VOLUME): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
        vol.Optional(
            CONF_RECEIVER_MAX_VOLUME, default=DEFAULT_RECEIVER_MAX_VOLUME
        ): cv.positive_int,
        vol.Optional(CONF_SOURCES, default=DEFAULT_SOURCES): {cv.string: cv.string},
    }
)

TIMEOUT_MESSAGE = "Timeout waiting for response."

ATTR_HDMI_OUTPUT = "hdmi_output"
ATTR_PRESET = "preset"
ATTR_AUDIO_INFORMATION = "audio_information"
ATTR_VIDEO_INFORMATION = "video_information"
ATTR_VIDEO_OUT = "video_out"

ACCEPTED_VALUES = [
    "no", "analog", "yes", "out", "out-sub", "sub", "hdbaset", "both", "up",
]
ONKYO_SELECT_OUTPUT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(ATTR_HDMI_OUTPUT): vol.In(ACCEPTED_VALUES),
    }
)
SERVICE_SELECT_HDMI_OUTPUT = "onkyo_select_hdmi_output"


def _parse_onkyo_payload(payload):
    if isinstance(payload, bool):
        return False
    if len(payload) < 2:
        return None
    if isinstance(payload[1], str):
        return payload[1].split(",")
    return payload[1]


def _tuple_get(tup, index, default=None):
    return (tup[index : index + 1] or [default])[0]


def determine_zones(receiver):
    """Determine available zones without crashing on parse errors."""
    out = {"zone2": False, "zone3": False}

    def _check(cmd_code: str, na_code: str, key: str) -> bool:
        try:
            _LOGGER.debug("Checking %s via raw(%s)", key, cmd_code)
            try:
                resp = receiver.raw(cmd_code)
            except Exception as err:
                _LOGGER.debug("Raw %s failed (%s), assuming not available", cmd_code, err)
                return False
            if isinstance(resp, tuple) and len(resp) >= 2 and resp[1] != na_code:
                return True
            _LOGGER.debug("%s not available or N/A: %s", key, resp)
            return False
        except ValueError as err:
            if str(err) != TIMEOUT_MESSAGE:
                raise
            _LOGGER.debug("%s query timed out, assuming not available", key)
            return False

    out["zone2"] = _check("ZPWQSTN", "ZPWN/A", "zone2")
    out["zone3"] = _check("PW3QSTN", "PW3N/A", "zone3")
    return out


def setup_platform(hass: HomeAssistant, config: ConfigType, add_entities: AddEntitiesCallback, discovery_info: DiscoveryInfoType | None = None) -> None:
    hosts: list[OnkyoDevice] = []

    def service_handle(service: ServiceCall) -> None:
        entity_ids = service.data[ATTR_ENTITY_ID]
        for device in [d for d in hosts if d.entity_id in entity_ids]:
            if service.service == SERVICE_SELECT_HDMI_OUTPUT:
                device.select_output(service.data[ATTR_HDMI_OUTPUT])

    hass.services.register(DOMAIN, SERVICE_SELECT_HDMI_OUTPUT, service_handle, schema=ONKYO_SELECT_OUTPUT_SCHEMA)

    if CONF_HOST in config and (host := config[CONF_HOST]) not in KNOWN_HOSTS:
        try:
            receiver = eISCP(host)
            hosts.append(OnkyoDevice(receiver, config.get(CONF_SOURCES), name=config.get(CONF_NAME), max_volume=config.get(CONF_MAX_VOLUME), receiver_max_volume=config.get(CONF_RECEIVER_MAX_VOLUME)))
            KNOWN_HOSTS.append(host)
            zones = determine_zones(receiver)
            if zones["zone2"]:
                hosts.append(OnkyoDeviceZone("2", receiver, config.get(CONF_SOURCES), name=f"{config[CONF_NAME]} Zone 2", max_volume=config.get(CONF_MAX_VOLUME), receiver_max_volume=config.get(CONF_RECEIVER_MAX_VOLUME)))
            if zones["zone3"]:
                hosts.append(OnkyoDeviceZone("3", receiver, config.get(CONF_SOURCES), name=f"{config[CONF_NAME]} Zone 3", max_volume=config.get(CONF_MAX_VOLUME), receiver_max_volume=config.get(CONF_RECEIVER_MAX_VOLUME)))
        except OSError:
            _LOGGER.error("Unable to connect to receiver at %s", host)
    else:
        for receiver in eISCP.discover():
            if receiver.host not in KNOWN_HOSTS:
                hosts.append(OnkyoDevice(receiver, config.get(CONF_SOURCES)))
                KNOWN_HOSTS.append(receiver.host)
    add_entities(hosts, True)


class OnkyoDevice(MediaPlayerEntity):
    _attr_supported_features = SUPPORT_ONKYO

    def __init__(self, receiver, sources, name=None, max_volume=SUPPORTED_MAX_VOLUME, receiver_max_volume=DEFAULT_RECEIVER_MAX_VOLUME):
        self._receiver = receiver
        self._host = getattr(receiver, 'host', None)
        self._port = getattr(receiver, 'port', None)
        try:
            sock = self._receiver.command_socket
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 300)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 60)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
        except Exception:
            _LOGGER.debug("Could not set TCP keepalive for %s", name or self._host)
        self._attr_is_volume_muted = False
        self._attr_volume_level = 0
        self._attr_state = MediaPlayerState.OFF
        if name:
            self._attr_name = name
        else:
            self._attr_unique_id = f"{receiver.info['model_name']}_{receiver.info['identifier']}"
            self._attr_name = self._attr_unique_id
        self._max_volume = max_volume
        self._receiver_max_volume = receiver_max_volume
        self._attr_source_list = list(sources.values())
        self._source_mapping = sources
        self._reverse_mapping = {v: k for k, v in sources.items()}
        self._attr_extra_state_attributes = {}
        self._hdmi_out_supported = True
        self._audio_info_supported = True
        self._video_info_supported = True

    def command(self, cmd: str):
        try:
            return self._receiver.command(cmd)
        except Exception as err:
            _LOGGER.warning("Command %r failed (%s), reconnecting…", cmd, err)
            try:
                self._receiver.disconnect()
            except Exception:
                pass
            self._receiver = eISCP(self._host, self._port) if self._port else eISCP(self._host)
            try:
                sock = self._receiver.command_socket
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 300)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 60)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
            except Exception:
                _LOGGER.debug("Could not reset keepalive on reconnect for %s", self._attr_name)
            try:
                return self._receiver.command(cmd)
            except Exception as err2:
                _LOGGER.error("Reconnect attempt also failed: %s", err2)
                return False

    def update(self) -> None:
        status = self.command("system-power query")
        if not status:
            return
        if status[1] == "on":
            self._attr_state = MediaPlayerState.ON
        else:
            self._attr_state = MediaPlayerState.OFF
            for attr in (ATTR_AUDIO_INFORMATION, ATTR_VIDEO_INFORMATION, ATTR_PRESET, ATTR_VIDEO_OUT):
                self._attr_extra_state_attributes.pop(attr, None)
            return
        volume_raw = self.command("volume query")
        mute_raw = self.command("audio-muting query")
        source_raw = self.command("input-selector query")
        hdmi_raw = self.command("hdmi-output-selector query") if self._hdmi_out_supported else []
        preset_raw = self.command("preset query")
        if self._audio_info_supported:
            self._parse_audio_information(self.command("audio-information query"))
        if self._video_info_supported:
            self._parse_video_information(self.command("video-information query"))
        if not (volume_raw and mute_raw and source_raw):
            return
        sources = _parse_onkyo_payload(source_raw)
        self._attr_source = next((self._source_mapping[s] for s in sources if s in self._source_mapping), "_".join(sources))
        if preset_raw and self.source and self.source.lower() == "radio":
            self._attr_extra_state_attributes[ATTR_PRESET] = preset_raw[1]
        self._attr_is_volume_muted = bool(mute_raw[1] == "on")
        self._attr_volume_level = volume_raw[1] / (self._receiver_max_volume * self._max_volume / 100)
        if hdmi_raw:
            self._attr_extra_state_attributes[ATTR_VIDEO_OUT] = ",".join(hdmi_raw[1])
            if hdmi_raw[1] == "N/A":
                self._hdmi_out_supported = False

    def turn_off(self) -> None:
        self.command("system-power standby")
    def set_volume_level(self, volume: float) -> None:
        self.command(f"volume {int(volume * (self._max_volume / 100) * self._receiver_max_volume)}")
    def volume_up(self) -> None:
        self.command("volume level-up")
    def volume_down(self) -> None:
        self.command("volume level-down")
    def mute_volume(self, mute: bool) -> None:
        self.command("audio-muting on" if mute else "audio-muting off")
    def turn_on(self) -> None:
        self.command("system-power on")
    def select_source(self, source: str) -> None:
        if self.source_list and source in self.source_list:
            source = self._reverse_mapping[source]
        self.command(f"input-selector {source}")
    def play_media(self, media_type: MediaType | str, media_id: str, **kwargs: Any) -> None:
        src = self._reverse_mapping.get(self._attr_source)
        if media_type.lower() == "radio" and src in DEFAULT_PLAYABLE_SOURCES:
            self.command(f"preset {media_id}")
    def select_output(self, output):
        self.command(f"hdmi-output-selector={output}")

    def _parse_audio_information(self, raw):
        vals = _parse_onkyo_payload(raw)
        if vals is False:
            self._audio_info_supported = False
            return
        if vals:
            self._attr_extra_state_attributes[ATTR_AUDIO_INFORMATION] = {
                "format": _tuple_get(vals, 1),
                "input_frequency": _tuple_get(vals, 2),
                "input_channels": _tuple_get(vals, 3),
                "listening_mode": _tuple_get(vals, 4),
                "output_channels": _tuple_get(vals, 5),
                "output_frequency": _tuple_get(vals, 6),
            }
        else:
            self._attr_extra_state_attributes.pop(ATTR_AUDIO_INFORMATION, None)
    def _parse_video_information(self, raw):
        vals = _parse_onkyo_payload(raw)
        if vals is False:
            self._video_info_supported = False
            return
        if vals:
            self._attr_extra_state_attributes[ATTR_VIDEO_INFORMATION] = {
                "input_resolution": _tuple_get(vals, 1),
                "input_color_schema": _tuple_get(vals, 2),
                "input_color_depth": _tuple_get(vals, 3),
                "output_resolution": _tuple_get(vals, 5),
                "output_color_schema": _tuple_get(vals, 6),
                "output_color_depth": _tuple_get(vals, 7),
                "picture_mode": _tuple_get(vals, 8),
                "dynamic_range": _tuple_get(vals, 9),
            }
        else:
            self._attr_extra_state_attributes.pop(ATTR_VIDEO_INFORMATION, None)

class OnkyoDeviceZone(OnkyoDevice):
    def __init__(self, zone, receiver, sources, name=None, max_volume=SUPPORTED_MAX_VOLUME, receiver_max_volume=DEFAULT_RECEIVER_MAX_VOLUME):
        self._zone = zone
        self._supports_volume = True
        super().__init__(receiver, sources, name, max_volume, receiver_max_volume)
    def update(self) -> None:
        status = self.command(f"zone{self._zone}.power=query")
        if not status:
            return
        if status[1] == "on":
            self._attr_state = MediaPlayerState.ON
        else:
            self._attr_state = MediaPlayerState.OFF
            return
        vol_raw = self.command(f"zone{self._zone}.volume=query")
        mute_raw = self.command(f"zone{self._zone}.muting=query")
        src_raw = self.command(f"zone{self._zone}.selector=query")
        preset_raw = self.command(f"zone{self._zone}.preset=query")
        if src_raw and not vol_raw:
            self._supports_volume = False
        if not (vol_raw and mute_raw and src_raw):
            return
        self._supports_volume = isinstance(vol_raw[1], (float, int))
        if isinstance(src_raw[1], str):
            srcs = (src_raw[0], (src_raw[1],))
        else:
            srcs = src_raw
        self._attr_source = next((self._source_mapping[s] for s in srcs[1] if s in self._source_mapping), "_".join(srcs[1]))
        self._attr_is_volume_muted = bool(mute_raw[1] == "on")
        if preset_raw and self.source and self.source.lower() == "radio":
            self._attr_extra_state_attributes[ATTR_PRESET] = preset_raw[1]
        if self._supports_volume:
            self._attr_volume_level = vol_raw[1] / (self._receiver_max_volume * self._max_volume / 100)
    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        return SUPPORT_ONKYO if self._supports_volume else SUPPORT_ONKYO_WO_VOLUME
    def turn_off(self) -> None:
        self.command(f"zone{self._zone}.power=standby")
    def set_volume_level(self, volume: float) -> None:
        self.command(f"zone{self._zone}.volume={int(volume * (self._max_volume / 100) * self._receiver_max_volume)}")
    def volume_up(self) -> None:
        self.command(f"zone{self._zone}.volume=level-up")
    def volume_down(self) -> None:
        self.command(f"zone{self._zone}.volume=level-down")
    def mute_volume(self, mute: bool) -> None:
        self.command(f"zone{self._zone}.muting=on" if mute else f"zone{self._zone}.muting=off")
    def turn_on(self) -> None:
        self.command(f"zone{self._zone}.power=on")
    def select_source(self, source: str) -> None:
        if self.source_list and source in self.source_list:
            source = self._reverse_mapping[source]
        self.command(f"zone{self._zone}.selector={source}")
