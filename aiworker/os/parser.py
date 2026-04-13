import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CPUInfo:
    cores: int
    model_name: str


@dataclass(frozen=True)
class MemoryInfo:
    total_mb: int
    available_mb: int


@dataclass(frozen=True)
class DiskInfo:
    mount_point: str
    total_gb: int
    used_percent: float


@dataclass(frozen=True)
class NetworkInfo:
    interface: str
    ip_address: str


@dataclass(frozen=True)
class SystemSnapshot:
    cpu: CPUInfo
    memory: MemoryInfo
    disks: list[DiskInfo]
    networks: list[NetworkInfo]
    os_name: str
    kernel_version: str


def parse_cpuinfo(raw: str) -> CPUInfo:
    cores: int = 0
    model_name: str = "unknown"

    if not raw.strip():
        return CPUInfo(cores=cores, model_name=model_name)

    model_found: bool = False
    for line in raw.splitlines():
        stripped: str = line.strip()
        if stripped.startswith("processor"):
            parts: list[str] = stripped.split(":", 1)
            if len(parts) == 2:
                cores += 1
        if not model_found and stripped.startswith("model name"):
            parts = stripped.split(":", 1)
            if len(parts) == 2:
                candidate: str = parts[1].strip()
                if candidate:
                    model_name = candidate
                    model_found = True

    return CPUInfo(cores=cores, model_name=model_name)


def parse_meminfo(raw: str) -> MemoryInfo:
    total_kb: int = 0
    available_kb: int = 0

    if not raw.strip():
        return MemoryInfo(total_mb=0, available_mb=0)

    for line in raw.splitlines():
        stripped: str = line.strip()
        if stripped.startswith("MemTotal:"):
            total_kb = _extract_kb_value(stripped)
        elif stripped.startswith("MemAvailable:"):
            available_kb = _extract_kb_value(stripped)

    return MemoryInfo(
        total_mb=total_kb // 1024,
        available_mb=available_kb // 1024,
    )


def _extract_kb_value(line: str) -> int:
    parts: list[str] = line.split(":", 1)
    if len(parts) < 2:
        return 0
    tokens: list[str] = parts[1].strip().split()
    if not tokens:
        return 0
    try:
        return int(tokens[0])
    except ValueError:
        return 0


def parse_df(raw: str) -> list[DiskInfo]:
    if not raw.strip():
        return []

    lines: list[str] = raw.strip().splitlines()
    if len(lines) < 2:
        return []

    results: list[DiskInfo] = []
    for line in lines[1:]:
        tokens: list[str] = line.split()
        if len(tokens) < 6:
            continue

        filesystem: str = tokens[0]
        if filesystem in ("tmpfs", "devtmpfs"):
            continue

        try:
            total_kb: int = int(tokens[1])
        except ValueError:
            continue

        use_str: str = tokens[4].rstrip("%")
        try:
            used_percent: float = float(use_str)
        except ValueError:
            used_percent = 0.0

        mount_point: str = tokens[5]
        total_gb: int = total_kb // (1024 * 1024)

        results.append(
            DiskInfo(
                mount_point=mount_point,
                total_gb=total_gb,
                used_percent=round(used_percent, 1),
            )
        )

    results.sort(key=lambda d: d.mount_point)
    return results


def parse_ip_addr(raw: str) -> list[NetworkInfo]:
    if not raw.strip():
        return []

    results: list[NetworkInfo] = []
    current_interface: str = ""

    for line in raw.splitlines():
        iface_match: re.Match[str] | None = re.match(
            r"^\d+:\s+(\S+?)(?:@\S+)?:\s+", line
        )
        if iface_match is not None:
            current_interface = iface_match.group(1)
            continue

        stripped: str = line.strip()
        inet_match: re.Match[str] | None = re.match(
            r"^inet\s+(\d+\.\d+\.\d+\.\d+)", stripped
        )
        if inet_match is not None and current_interface:
            ip: str = inet_match.group(1)
            if ip == "127.0.0.1":
                continue
            results.append(
                NetworkInfo(
                    interface=current_interface,
                    ip_address=ip,
                )
            )

    results.sort(key=lambda n: n.interface)
    return results


def parse_os_release(raw: str) -> str:
    if not raw.strip():
        return "unknown"

    for line in raw.splitlines():
        stripped: str = line.strip()
        if stripped.startswith("PRETTY_NAME="):
            value: str = stripped.split("=", 1)[1]
            value = value.strip('"').strip("'")
            if value:
                return value

    return "unknown"
