from dataclasses import dataclass
import json
import subprocess

from PyQt6.QtSerialPort import QSerialPortInfo


BLUETOOTH_KEYWORDS = (
    "bluetooth",
    "bth",
    "rfcomm",
    "spp",
    "standard serial over bluetooth",
)


@dataclass(frozen=True)
class BluetoothSerialDevice:
    port_name: str | None
    name: str
    description: str = ""
    manufacturer: str = ""
    serial_number: str = ""
    system_location: str = ""
    instance_id: str = ""
    status: str = ""
    source: str = "serial"

    @property
    def key(self):
        return self.port_name or self.instance_id or self.name

    @property
    def display_name(self):
        if not self.port_name:
            status = f" - {self.status}" if self.status else ""
            return f"{self.name} (未映射串口{status})"

        detail = self.description or self.manufacturer or self.system_location
        if detail and detail != self.name:
            return f"{self.name} ({self.port_name}) - {detail}"
        return f"{self.name} ({self.port_name})"

    @property
    def can_open_serial(self):
        return bool(self.port_name)


def scan_bluetooth_devices():
    devices_by_key = {}
    for device in scan_local_bluetooth_serial_devices():
        devices_by_key[device.key] = device

    for device in scan_windows_bluetooth_devices():
        devices_by_key.setdefault(device.key, device)

    return list(devices_by_key.values())


def scan_bluetooth_serial_devices():
    return [device for device in scan_bluetooth_devices() if device.can_open_serial]


def scan_local_bluetooth_serial_devices():
    devices = []
    for port in QSerialPortInfo.availablePorts():
        fields = (
            port.portName(),
            port.description(),
            port.manufacturer(),
            port.serialNumber(),
            port.systemLocation(),
        )
        searchable = " ".join(value for value in fields if value).lower()
        if not any(keyword in searchable for keyword in BLUETOOTH_KEYWORDS):
            continue

        description = port.description()
        name = description if description else port.portName()
        devices.append(
            BluetoothSerialDevice(
                port_name=port.portName(),
                name=name,
                description=description,
                manufacturer=port.manufacturer(),
                serial_number=port.serialNumber(),
                system_location=port.systemLocation(),
            )
        )

    return devices


def merge_bluetooth_devices(*device_groups):
    devices_by_key = {}
    for group in device_groups:
        for device in group:
            devices_by_key.setdefault(device.key, device)
    return list(devices_by_key.values())


def windows_bluetooth_scan_command():
    return (
        "$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
        "Get-PnpDevice -Class Bluetooth | "
        "Where-Object { $_.FriendlyName -and "
        "($_.InstanceId -like 'BTHENUM\\DEV_*' -or $_.InstanceId -like 'BTHLEDEVICE\\*') } | "
        "Select-Object Status,FriendlyName,InstanceId | ConvertTo-Json -Depth 3"
    )


def parse_windows_bluetooth_devices(stdout):
    if not stdout.strip():
        return []

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        payload = [payload]

    devices = []
    for item in payload:
        name = str(item.get("FriendlyName") or "").strip()
        instance_id = str(item.get("InstanceId") or "").strip()
        if not name or not instance_id:
            continue
        devices.append(
            BluetoothSerialDevice(
                port_name=None,
                name=name,
                instance_id=instance_id,
                status=str(item.get("Status") or "").strip(),
                source="pnp",
            )
        )

    return devices


def scan_windows_bluetooth_devices(timeout_seconds=25):
    command = windows_bluetooth_scan_command()

    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    if completed.returncode != 0 or not completed.stdout.strip():
        return []

    return parse_windows_bluetooth_devices(completed.stdout)
