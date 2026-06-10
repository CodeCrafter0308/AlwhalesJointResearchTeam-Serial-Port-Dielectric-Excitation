import asyncio
from dataclasses import dataclass, field
import re
import threading

from PyQt6.QtCore import QObject, pyqtSignal

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # pragma: no cover - runtime dependency guard
    BleakClient = None
    BleakScanner = None


KNOWN_BLE_NAME_BY_ADDRESS = {
    "F8:2E:0C:C9:35:B3": "TV281u-0CC985B",
}


@dataclass(frozen=True)
class BleDeviceRecord:
    address: str
    name: str = ""
    name_source: str = ""
    rssi: int | None = None
    service_uuids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self):
        return f"ble:{self.address}"

    @property
    def display_name(self):
        name = self.name or "Unknown BLE Device"
        source_text = "" if not self.name_source else f" [{self.name_source}]"
        rssi_text = "" if self.rssi is None else f" RSSI={self.rssi}"
        return f"{self.address} {name}{source_text}{rssi_text}"

    @property
    def can_open_ble(self):
        return True

    @property
    def can_open_serial(self):
        return False


class BleManager(QObject):
    scan_started = pyqtSignal()
    scan_finished = pyqtSignal(object, str)
    status_changed = pyqtSignal(str)
    services_ready = pyqtSignal(object, str)
    transmit_started = pyqtSignal(str)
    connected = pyqtSignal(str)
    disconnected = pyqtSignal(str)
    data_received = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._loop = None
        self._client = None
        self._stop_event = threading.Event()
        self._connected = False
        self._write_characteristic = None
        self._write_with_response = True
        self._notify_characteristics = []
        self._transmit_started = False

    @property
    def is_available(self):
        return BleakScanner is not None and BleakClient is not None

    @property
    def is_connected(self):
        return self._connected

    @property
    def has_write_characteristic(self):
        return self._write_characteristic is not None

    def start_scan(self, timeout=6.0):
        if not self.is_available:
            self.scan_finished.emit([], "未安装 bleak，无法按 LightBlue 的 BLE/GATT 流程扫描。")
            return
        if self._thread and self._thread.is_alive():
            self.status_changed.emit("BLE 操作仍在进行...")
            return

        self.scan_started.emit()
        self._thread = threading.Thread(target=self._run_scan, args=(timeout,), daemon=True)
        self._thread.start()

    def connect_device(self, address):
        if not self.is_available:
            self.error.emit("未安装 bleak，无法连接 BLE 设备。")
            return
        if self._thread and self._thread.is_alive():
            self.error.emit("BLE 操作仍在进行，请稍后再连接。")
            return

        self.disconnect()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_connect, args=(address,), daemon=True)
        self._thread.start()

    def disconnect(self):
        self._stop_event.set()

    def start_data_transmit(self):
        if not self._loop or not self._client or not self._connected:
            self.error.emit("BLE 尚未连接，无法进入 Data Transmit。")
            return False
        future = asyncio.run_coroutine_threadsafe(self._start_notifications(), self._loop)
        future.add_done_callback(self._on_transmit_start_done)
        return True

    def write(self, payload):
        if not self._loop or not self._client or not self._write_characteristic:
            self.error.emit("BLE 设备没有可写 Characteristic，无法发送命令。")
            return False

        future = asyncio.run_coroutine_threadsafe(
            self._client.write_gatt_char(
                self._write_characteristic,
                payload,
                response=self._write_with_response,
            ),
            self._loop,
        )
        future.add_done_callback(self._on_write_done)
        return True

    def _run_scan(self, timeout):
        try:
            devices = asyncio.run(self._scan(timeout))
            self.scan_finished.emit(devices, "")
        except Exception as exc:  # pragma: no cover - depends on BLE stack
            self.scan_finished.emit([], f"BLE 扫描失败：{exc}")

    async def _scan(self, timeout):
        try:
            discovered = await BleakScanner.discover(
                timeout=timeout,
                return_adv=True,
                scanning_mode="active",
            )
        except TypeError:
            discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
        records = []

        if isinstance(discovered, dict):
            iterable = discovered.values()
            for device, advertisement in iterable:
                service_uuids = tuple(getattr(advertisement, "service_uuids", None) or ())
                name, name_source = self._resolve_device_name(device, advertisement)
                records.append(
                    BleDeviceRecord(
                        address=device.address,
                        name=name,
                        name_source=name_source,
                        rssi=getattr(advertisement, "rssi", None),
                        service_uuids=service_uuids,
                    )
                )
        else:
            for device in discovered:
                records.append(
                    BleDeviceRecord(
                        address=device.address,
                        name=device.name or "",
                        name_source="adv" if device.name else "",
                        rssi=getattr(device, "rssi", None),
                    )
                )

        records.sort(key=lambda item: (item.name == "", item.name.lower(), -(item.rssi or -999), item.address))
        return records

    @staticmethod
    def _resolve_device_name(device, advertisement):
        device_name = BleManager._clean_bluetooth_name(getattr(device, "name", None) or "")
        if device_name:
            return device_name, "adv"

        local_name = BleManager._clean_bluetooth_name(getattr(advertisement, "local_name", None) or "")
        if local_name:
            return local_name, "scan response"

        known_name = BleManager._known_name_from_address(getattr(device, "address", "") or "")
        if known_name:
            return known_name, "known"

        name = BleManager._name_from_binary_payloads(
            getattr(advertisement, "manufacturer_data", None) or {},
            getattr(advertisement, "service_data", None) or {},
        )
        if name:
            return name, "manufacturer"

        return "", ""

    @staticmethod
    def _clean_bluetooth_name(name):
        name = name.strip()
        if not name:
            return ""
        if name.lower() in {"unknown", "unknown ble device"}:
            return ""
        if BleManager._looks_like_random_token(name):
            return ""
        return name

    @staticmethod
    def _known_name_from_address(address):
        normalized = BleManager._normalize_address(address)
        return KNOWN_BLE_NAME_BY_ADDRESS.get(normalized, "")

    @staticmethod
    def _normalize_address(address):
        text = str(address).strip().upper().replace("-", ":")
        parts = [part.zfill(2) for part in text.split(":") if part]
        return ":".join(parts)

    @staticmethod
    def _name_from_binary_payloads(*payload_maps):
        candidates = []
        for payload_map in payload_maps:
            for payload in payload_map.values():
                candidates.extend(BleManager._extract_name_candidates(bytes(payload)))

        if not candidates:
            return ""

        candidates.sort(key=lambda item: (len(item), item.lower()), reverse=True)
        return candidates[0]

    @staticmethod
    def _extract_name_candidates(payload):
        try:
            decoded = payload.decode("utf-8", errors="ignore")
        except UnicodeDecodeError:
            return []

        candidates = []
        for match in re.finditer(r"[A-Za-z][A-Za-z0-9 _.\-]{2,}", decoded):
            candidate = match.group(0).strip(" _.-")
            if len(candidate) < 5:
                continue
            if len(candidate) < 10 and " " not in candidate and "-" not in candidate and not any(character.isdigit() for character in candidate):
                continue
            if not any(character.isalpha() for character in candidate):
                continue
            if BleManager._looks_like_random_token(candidate):
                continue
            candidates.append(candidate)
        return candidates

    @staticmethod
    def _looks_like_random_token(text):
        if len(text) >= 16 and re.fullmatch(r"[A-Za-z0-9+/=]+", text):
            return True
        if len(text) <= 5 and any(ch.isdigit() for ch in text):
            return True
        if len(text) < 8:
            return False
        alpha = sum(ch.isalpha() for ch in text)
        digit = sum(ch.isdigit() for ch in text)
        if digit and alpha and digit / len(text) > 0.35:
            return True
        return False

    def _run_connect(self, address):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_listen(address))
        except Exception as exc:  # pragma: no cover - depends on BLE device
            self.error.emit(f"BLE 连接失败：{exc}")
        finally:
            self._connected = False
            self._write_characteristic = None
            self._notify_characteristics = []
            self._transmit_started = False
            self._client = None
            self._loop.close()
            self._loop = None
            self.disconnected.emit("BLE 已断开")

    async def _connect_and_listen(self, address):
        def on_disconnected(_client):
            self._stop_event.set()

        self.status_changed.emit(f"正在连接 BLE：{address}")
        async with BleakClient(address, disconnected_callback=on_disconnected, timeout=20.0) as client:
            self._client = client
            self._connected = True
            services = list(client.services)
            write_count = 0
            connected_name = await self._read_standard_device_name(client)
            services_info = []
            self._notify_characteristics = []

            for service in services:
                characteristics_info = []
                for characteristic in service.characteristics:
                    properties = set(characteristic.properties or [])
                    if self._write_characteristic is None and (
                        "write" in properties or "write-without-response" in properties
                    ):
                        self._write_characteristic = characteristic.uuid
                        self._write_with_response = "write" in properties
                    if "write" in properties or "write-without-response" in properties:
                        write_count += 1

                    if "notify" in properties or "indicate" in properties:
                        self._notify_characteristics.append(characteristic.uuid)
                    characteristics_info.append(
                        {
                            "uuid": characteristic.uuid,
                            "description": getattr(characteristic, "description", "") or "",
                            "properties": sorted(properties),
                        }
                    )

                services_info.append(
                    {
                        "uuid": service.uuid,
                        "description": getattr(service, "description", "") or "",
                        "characteristics": characteristics_info,
                    }
                )

            self.connected.emit(
                f"BLE 已连接{f'：{connected_name}' if connected_name else ''}；"
                f"服务 {len(services)} 个，Notify/Indicate {len(self._notify_characteristics)} 个，"
                f"可写 {write_count} 个"
            )
            self.services_ready.emit(services_info, connected_name)

            while not self._stop_event.is_set() and client.is_connected:
                await asyncio.sleep(0.2)

    def _on_notification(self, _sender, payload):
        self._emit_payload(payload)

    async def _start_notifications(self):
        if self._transmit_started:
            return "Data Transmit 已在运行"
        if not self._notify_characteristics:
            raise RuntimeError("该设备未发现 Notify/Indicate Characteristic。")
        for uuid in self._notify_characteristics:
            await self._client.start_notify(uuid, self._on_notification)
        self._transmit_started = True
        return f"Data Transmit 已启动：订阅 {len(self._notify_characteristics)} 个 Notify/Indicate Characteristic"

    async def _read_standard_device_name(self, client):
        try:
            payload = await client.read_gatt_char("00002a00-0000-1000-8000-00805f9b34fb")
        except Exception:
            return ""
        return self._clean_bluetooth_name(bytes(payload).decode("utf-8", errors="ignore"))

    def _emit_payload(self, payload):
        raw = bytes(payload)
        text = raw.decode("utf-8", errors="replace")
        self.data_received.emit(text)

    def _on_write_done(self, future):
        try:
            future.result()
        except Exception as exc:  # pragma: no cover - depends on BLE stack
            self.error.emit(f"BLE 发送失败：{exc}")

    def _on_transmit_start_done(self, future):
        try:
            message = future.result()
        except Exception as exc:  # pragma: no cover - depends on BLE stack
            self.error.emit(f"Data Transmit 启动失败：{exc}")
            return
        self.transmit_started.emit(message)
