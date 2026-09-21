"""Volume principal Windows (pycaw), avec repli sur les touches multimédia."""
from __future__ import annotations

import logging
from contextlib import contextmanager

from .keyboard import MEDIA, press_vk
from ..replies import R

log = logging.getLogger("sentinel.audio")


@contextmanager
def _com():
    """Initialise COM pour le thread courant (chaque commande tourne dans son thread)."""
    import comtypes

    inited = False
    try:
        comtypes.CoInitialize()
        inited = True
    except OSError:
        pass
    try:
        yield
    finally:
        if inited:
            comtypes.CoUninitialize()


def _endpoint():
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    speakers = AudioUtilities.GetSpeakers()
    if hasattr(speakers, "EndpointVolume"):          # pycaw récent
        return speakers.EndpointVolume
    iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)  # pycaw ancien
    return cast(iface, POINTER(IAudioEndpointVolume))


class SystemAudio:
    def __init__(self, cfg) -> None:
        self.cfg = cfg

    # -- lecture / écriture -------------------------------------------------
    def get_percent(self) -> int:
        with _com():
            ep = _endpoint()
            try:
                return round(ep.GetMasterVolumeLevelScalar() * 100)
            finally:
                del ep

    def _set(self, percent: int) -> None:
        percent = max(0, min(100, int(percent)))
        try:
            with _com():
                ep = _endpoint()
                try:
                    ep.SetMasterVolumeLevelScalar(percent / 100.0, None)
                    if percent > 0:
                        ep.SetMute(0, None)
                finally:
                    del ep
        except Exception:
            log.exception("pycaw indisponible, repli sur les touches volume")
            press_vk(MEDIA["voldown"], 50)               # chaque appui = 2 %
            press_vk(MEDIA["volup"], percent // 2)

    # -- commandes ----------------------------------------------------------
    def set_percent(self, percent: int) -> str:
        self._set(percent)
        return R(self.cfg, "volume_set", p=percent)

    def change(self, direction: int, amount: int | None) -> str:
        step = amount if amount is not None else int(self.cfg["volume_step"])
        try:
            current = self.get_percent()
        except Exception:
            log.exception("lecture du volume impossible")
            press_vk(MEDIA["volup" if direction > 0 else "voldown"], max(1, step // 2))
            return R(self.cfg, "volume_adjusted")
        target = max(0, min(100, current + direction * step))
        self._set(target)
        return R(self.cfg, "volume_change", p=target)

    def mute(self, mute: bool) -> str:
        try:
            with _com():
                ep = _endpoint()
                try:
                    ep.SetMute(1 if mute else 0, None)
                finally:
                    del ep
        except Exception:
            log.exception("mute via pycaw impossible, repli touche multimédia")
            press_vk(MEDIA["mute"])
        return R(self.cfg, "mute_on" if mute else "mute_off")

    def describe(self) -> str:
        try:
            return R(self.cfg, "volume_get", p=self.get_percent())
        except Exception:
            return R(self.cfg, "volume_read_error")
