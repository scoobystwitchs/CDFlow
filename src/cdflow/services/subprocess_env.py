"""Environment isolation for host tools launched by a frozen CDFlow build."""

from __future__ import annotations

import os
import sys

_FROZEN_GSTREAMER_VARIABLES = (
    "GST_PLUGIN_PATH",
    "GST_PLUGIN_SYSTEM_PATH",
    "GST_REGISTRY",
    "GST_REGISTRY_FORK",
)


def host_process_environment(*, gstreamer: bool = False) -> dict[str, str]:
    """Return an environment that will not inject bundled libraries into host tools.

    PyInstaller adjusts the dynamic-loader and GStreamer search paths for the
    embedded runtime. Those paths are correct in-process, but a Fedora binary
    such as ffmpeg, lsblk, or gst-launch must resolve against its matching host
    libraries and plug-ins.
    """

    environment = dict(os.environ)
    if not getattr(sys, "frozen", False):
        return environment

    original_library_path = environment.pop("LD_LIBRARY_PATH_ORIG", None)
    if original_library_path:
        environment["LD_LIBRARY_PATH"] = original_library_path
    else:
        environment.pop("LD_LIBRARY_PATH", None)

    if gstreamer:
        for name in _FROZEN_GSTREAMER_VARIABLES:
            environment.pop(name, None)
    return environment


__all__ = ["host_process_environment"]
