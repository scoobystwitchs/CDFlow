"""Event-driven optical-drive monitoring through UDisks2 and D-Bus."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from contextlib import suppress
from typing import Any

from cdflow.app.constants import (
    UDISKS_BLOCK_INTERFACE,
    UDISKS_DRIVE_INTERFACE,
    UDISKS_FILESYSTEM_INTERFACE,
    UDISKS_OBJECT_MANAGER,
    UDISKS_ROOT,
    UDISKS_SERVICE,
)
from cdflow.models.disc import Drive

from ._qt import QObject, Signal

try:  # dbus-next is intentionally optional at module-import time
    from dbus_next import BusType, Message, MessageType, Variant
    from dbus_next.aio import MessageBus

    DBUS_NEXT_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on host installation
    BusType = Message = MessageType = Variant = MessageBus = None  # type: ignore[assignment]
    DBUS_NEXT_AVAILABLE = False

DBUS_PROPERTIES = "org.freedesktop.DBus.Properties"
DBUS_SERVICE = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
DBUS_INTERFACE = "org.freedesktop.DBus"


class DriveMonitor(QObject):
    """Maintain an optical-drive snapshot from UDisks2 signals.

    A dedicated asyncio thread owns the D-Bus connection.  Qt signals safely
    cross back to the GUI thread, avoiding an asyncio/Qt event-loop dependency.
    No timer or device polling loop is used.
    """

    monitor_ready = Signal()
    monitor_stopped = Signal()
    availability_changed = Signal(bool)
    drives_changed = Signal(object)
    drive_added = Signal(object)
    drive_removed = Signal(str)
    drive_changed = Signal(object)
    media_inserted = Signal(object)
    media_removed = Signal(object)
    error_occurred = Signal(str)
    operation_finished = Signal(str, str, bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._bus: Any = None
        self._objects: dict[str, dict[str, dict[str, Any]]] = {}
        self._drives: dict[str, Drive] = {}
        self._media_tokens: dict[str, tuple[Any, ...]] = {}
        self._refresh_task: asyncio.Task[None] | None = None

    @property
    def drives(self) -> tuple[Drive, ...]:
        with self._thread_lock:
            return tuple(sorted(self._drives.values(), key=_drive_sort_key))

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if not DBUS_NEXT_AVAILABLE:
            self.availability_changed.emit(False)
            self.error_occurred.emit("dbus-next is not installed; automatic optical-drive detection is unavailable")
            self.monitor_stopped.emit()
            return
        with self._thread_lock:
            if self.running:
                return
            self._thread = threading.Thread(
                target=self._thread_main,
                name="cdflow-udisks-monitor",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, wait: bool = True) -> None:
        with self._thread_lock:
            loop = self._loop
            stop_event = self._stop_event
            thread = self._thread
        if loop and stop_event and loop.is_running():
            loop.call_soon_threadsafe(stop_event.set)
        if wait and thread and thread is not threading.current_thread():
            thread.join(timeout=3.0)

    def eject(self, drive_object_path: str) -> None:
        self._schedule_operation("eject", drive_object_path, self._eject(drive_object_path))

    def mount(self, drive_or_block_path: str, *, read_only: bool = True) -> None:
        self._schedule_operation("mount", drive_or_block_path, self._mount(drive_or_block_path, read_only=read_only))

    def unmount(self, drive_or_block_path: str, *, force: bool = False) -> None:
        self._schedule_operation("unmount", drive_or_block_path, self._unmount(drive_or_block_path, force=force))

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as error:
            self.error_occurred.emit(f"UDisks2 monitor stopped: {error}")
        finally:
            with self._thread_lock:
                self._loop = None
                self._stop_event = None
                self._bus = None
                self._thread = None
            self.availability_changed.emit(False)
            self.monitor_stopped.emit()

    async def _run(self) -> None:
        assert MessageBus is not None and BusType is not None
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        with self._thread_lock:
            self._loop = loop
            self._stop_event = stop_event
        try:
            bus = await asyncio.wait_for(MessageBus(bus_type=BusType.SYSTEM).connect(), timeout=8)
        except Exception as error:
            self.error_occurred.emit(f"cannot connect to the system D-Bus: {error}")
            return
        with self._thread_lock:
            self._bus = bus
        bus.add_message_handler(self._handle_message)
        try:
            await self._add_signal_matches()
            await self._refresh_objects()
            self.availability_changed.emit(True)
            self.monitor_ready.emit()
            await stop_event.wait()
        finally:
            if self._refresh_task and not self._refresh_task.done():
                self._refresh_task.cancel()
            with suppress(Exception):
                bus.remove_message_handler(self._handle_message)
            bus.disconnect()

    async def _add_signal_matches(self) -> None:
        rules = (
            "type='signal',sender='org.freedesktop.UDisks2',"
            "interface='org.freedesktop.DBus.ObjectManager',"
            "path='/org/freedesktop/UDisks2'",
            "type='signal',sender='org.freedesktop.UDisks2',"
            "interface='org.freedesktop.DBus.Properties',"
            "path_namespace='/org/freedesktop/UDisks2'",
            "type='signal',sender='org.freedesktop.DBus',"
            "interface='org.freedesktop.DBus',member='NameOwnerChanged',"
            "arg0='org.freedesktop.UDisks2'",
        )
        for rule in rules:
            await self._call(
                destination=DBUS_SERVICE,
                path=DBUS_PATH,
                interface=DBUS_INTERFACE,
                member="AddMatch",
                signature="s",
                body=[rule],
            )

    async def _refresh_objects(self) -> None:
        reply = await self._call(
            destination=UDISKS_SERVICE,
            path=UDISKS_ROOT,
            interface=UDISKS_OBJECT_MANAGER,
            member="GetManagedObjects",
        )
        managed = reply.body[0] if reply.body else {}
        self._objects = _unwrap_managed_objects(managed)
        self._publish_drives()

    def _handle_message(self, message: Any) -> None:
        if MessageType is None or message.message_type != MessageType.SIGNAL:
            return None
        try:
            if message.interface == UDISKS_OBJECT_MANAGER and message.member == "InterfacesAdded":
                path, interfaces = message.body
                cached = self._objects.setdefault(str(path), {})
                cached.update(_unwrap_interfaces(interfaces))
                self._publish_drives()
            elif message.interface == UDISKS_OBJECT_MANAGER and message.member == "InterfacesRemoved":
                path, interfaces = message.body
                cached = self._objects.get(str(path), {})
                for interface in interfaces:
                    cached.pop(str(interface), None)
                if not cached:
                    self._objects.pop(str(path), None)
                self._publish_drives()
            elif message.interface == DBUS_PROPERTIES and message.member == "PropertiesChanged":
                interface, changed, invalidated = message.body
                cached = self._objects.setdefault(str(message.path), {}).setdefault(str(interface), {})
                cached.update({str(key): _unwrap(value) for key, value in changed.items()})
                if invalidated:
                    self._request_refresh()
                else:
                    self._publish_drives()
            elif message.interface == DBUS_INTERFACE and message.member == "NameOwnerChanged":
                name, _old_owner, new_owner = message.body
                if name == UDISKS_SERVICE and not new_owner:
                    self._objects.clear()
                    self._publish_drives()
                    self.availability_changed.emit(False)
                elif name == UDISKS_SERVICE and new_owner:
                    self._request_refresh()
                    self.availability_changed.emit(True)
        except Exception as error:
            self.error_occurred.emit(f"could not process a UDisks2 event: {error}")
        return None

    def _request_refresh(self) -> None:
        if self._refresh_task and not self._refresh_task.done():
            return

        async def refresh_after_signal_burst() -> None:
            await asyncio.sleep(0)
            try:
                await self._refresh_objects()
            except Exception as error:
                self.error_occurred.emit(f"could not refresh UDisks2 objects: {error}")

        self._refresh_task = asyncio.create_task(refresh_after_signal_burst())

    def _publish_drives(self) -> None:
        new_drives = {drive.object_path: drive for drive in _build_drives(self._objects)}
        new_tokens = {path: _media_token(path, self._objects, drive) for path, drive in new_drives.items()}
        with self._thread_lock:
            old_drives = self._drives
            old_tokens = self._media_tokens
            self._drives = new_drives
            self._media_tokens = new_tokens

        for path in sorted(old_drives.keys() - new_drives.keys()):
            old = old_drives[path]
            if old.media_available:
                self.media_removed.emit(old)
            self.drive_removed.emit(path)
        for path in sorted(new_drives.keys() - old_drives.keys()):
            drive = new_drives[path]
            self.drive_added.emit(drive)
            if drive.media_available:
                self.media_inserted.emit(drive)
        for path in sorted(new_drives.keys() & old_drives.keys()):
            old = old_drives[path]
            new = new_drives[path]
            token_changed = old_tokens.get(path) != new_tokens.get(path)
            if old != new:
                self.drive_changed.emit(new)
            if old.media_available and (not new.media_available or token_changed):
                self.media_removed.emit(old)
            if new.media_available and (not old.media_available or token_changed):
                self.media_inserted.emit(new)
        if old_drives != new_drives:
            self.drives_changed.emit(tuple(sorted(new_drives.values(), key=_drive_sort_key)))

    def _schedule_operation(
        self,
        operation: str,
        object_path: str,
        coroutine: Coroutine[Any, Any, str],
    ) -> None:
        with self._thread_lock:
            loop = self._loop
            bus = self._bus
        if not loop or not loop.is_running() or bus is None:
            coroutine.close()
            self.operation_finished.emit(operation, object_path, False, "UDisks2 is not connected")
            return
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)

        def finished(result: Any) -> None:
            try:
                message = str(result.result())
            except Exception as error:
                self.operation_finished.emit(operation, object_path, False, str(error))
            else:
                self.operation_finished.emit(operation, object_path, True, message)

        future.add_done_callback(finished)

    async def _eject(self, drive_object_path: str) -> str:
        await self._call(
            destination=UDISKS_SERVICE,
            path=drive_object_path,
            interface=UDISKS_DRIVE_INTERFACE,
            member="Eject",
            signature="a{sv}",
            body=[{}],
            timeout=30,
        )
        return "Disc ejected"

    async def _mount(self, drive_or_block_path: str, *, read_only: bool) -> str:
        block_path = self._resolve_block_path(drive_or_block_path)
        options: dict[str, Any] = {}
        if read_only:
            assert Variant is not None
            options["options"] = Variant("s", "ro")
        reply = await self._call(
            destination=UDISKS_SERVICE,
            path=block_path,
            interface=UDISKS_FILESYSTEM_INTERFACE,
            member="Mount",
            signature="a{sv}",
            body=[options],
            timeout=30,
        )
        mount_path = str(reply.body[0]) if reply.body else ""
        return mount_path or "Disc mounted"

    async def _unmount(self, drive_or_block_path: str, *, force: bool) -> str:
        block_path = self._resolve_block_path(drive_or_block_path)
        options: dict[str, Any] = {}
        if force:
            assert Variant is not None
            options["force"] = Variant("b", True)
        await self._call(
            destination=UDISKS_SERVICE,
            path=block_path,
            interface=UDISKS_FILESYSTEM_INTERFACE,
            member="Unmount",
            signature="a{sv}",
            body=[options],
            timeout=30,
        )
        return "Disc unmounted"

    def _resolve_block_path(self, path: str) -> str:
        if UDISKS_BLOCK_INTERFACE in self._objects.get(path, {}):
            return path
        drive = self._drives.get(path)
        if drive and drive.block_path:
            return drive.block_path
        raise RuntimeError("no filesystem block device is associated with this optical drive")

    async def _call(
        self,
        *,
        destination: str,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: list[Any] | None = None,
        timeout: float = 10,
    ) -> Any:
        if self._bus is None or Message is None or MessageType is None:
            raise RuntimeError("D-Bus is not connected")
        message = Message(
            destination=destination,
            path=path,
            interface=interface,
            member=member,
            signature=signature,
            body=body or [],
        )
        reply = await asyncio.wait_for(self._bus.call(message), timeout=timeout)
        if reply.message_type == MessageType.ERROR:
            detail = str(reply.body[0]) if reply.body else str(reply.error_name or "D-Bus call failed")
            raise RuntimeError(detail)
        return reply


def _unwrap(value: Any) -> Any:
    if hasattr(value, "value") and hasattr(value, "signature"):
        return _unwrap(value.value)
    if isinstance(value, dict):
        return {str(key): _unwrap(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_unwrap(item) for item in value]
    return value


def _unwrap_interfaces(interfaces: Any) -> dict[str, dict[str, Any]]:
    return {
        str(interface): {str(key): _unwrap(value) for key, value in properties.items()}
        for interface, properties in interfaces.items()
    }


def _unwrap_managed_objects(objects: Any) -> dict[str, dict[str, dict[str, Any]]]:
    return {str(path): _unwrap_interfaces(interfaces) for path, interfaces in objects.items()}


def _build_drives(objects: dict[str, dict[str, dict[str, Any]]]) -> list[Drive]:
    blocks_by_drive: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for path, interfaces in objects.items():
        block = interfaces.get(UDISKS_BLOCK_INTERFACE)
        if not block:
            continue
        drive_path = str(block.get("Drive") or "")
        blocks_by_drive.setdefault(drive_path, []).append((path, block))

    drives: list[Drive] = []
    for path, interfaces in objects.items():
        properties = interfaces.get(UDISKS_DRIVE_INTERFACE)
        if not properties:
            continue
        blocks = blocks_by_drive.get(path, [])
        if not _is_optical(properties, blocks):
            continue
        block_path, block = _preferred_block(blocks)
        device = _decode_udisks_bytes(block.get("PreferredDevice") or block.get("Device") or b"")
        drives.append(
            Drive(
                object_path=path,
                block_path=block_path,
                device=device,
                model=str(properties.get("Model") or "Optical Drive").strip(),
                vendor=str(properties.get("Vendor") or "").strip(),
                connection_bus=str(properties.get("ConnectionBus") or ""),
                media_available=bool(properties.get("MediaAvailable", False)),
                media_name=str(properties.get("Media") or block.get("IdLabel") or ""),
                audio_tracks=int(properties.get("OpticalNumAudioTracks") or 0),
                data_tracks=int(properties.get("OpticalNumDataTracks") or 0),
                can_eject=bool(properties.get("Ejectable", True)),
            )
        )
    return drives


def _preferred_block(blocks: list[tuple[str, dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    if not blocks:
        return "", {}
    return min(
        blocks,
        key=lambda pair: (
            not _decode_udisks_bytes(pair[1].get("Device") or b"").startswith("/dev/sr"),
            bool(pair[1].get("HintIgnore", False)),
            pair[0],
        ),
    )


def _is_optical(properties: dict[str, Any], blocks: list[tuple[str, dict[str, Any]]]) -> bool:
    if bool(properties.get("Optical", False)):
        return True
    compatibility = properties.get("MediaCompatibility") or []
    if any(str(item).startswith("optical") for item in compatibility):
        return True
    return any(_decode_udisks_bytes(block.get("Device") or b"").startswith("/dev/sr") for _path, block in blocks)


def _decode_udisks_bytes(value: Any) -> str:
    if isinstance(value, bytes):
        return value.rstrip(b"\0").decode("utf-8", "surrogateescape")
    if isinstance(value, list) and all(isinstance(item, int) for item in value):
        return bytes(value).rstrip(b"\0").decode("utf-8", "surrogateescape")
    return str(value or "").rstrip("\0")


def _media_token(
    path: str,
    objects: dict[str, dict[str, dict[str, Any]]],
    drive: Drive,
) -> tuple[Any, ...]:
    properties = objects.get(path, {}).get(UDISKS_DRIVE_INTERFACE, {})
    return (
        drive.media_available,
        properties.get("TimeMediaDetected", 0),
        drive.media_name,
        drive.audio_tracks,
        drive.data_tracks,
        drive.block_path,
        drive.device,
    )


def _drive_sort_key(drive: Drive) -> tuple[str, str]:
    return drive.display_name.casefold(), drive.device


__all__ = ["DBUS_NEXT_AVAILABLE", "DriveMonitor"]
