from __future__ import annotations

from aiworker.os.parser import (
    CPUInfo,
    MemoryInfo,
    SystemSnapshot,
    parse_cpuinfo,
    parse_df,
    parse_ip_addr,
    parse_meminfo,
    parse_os_release,
)


class SystemIntrospector:
    def __init__(self, runner: object) -> None:
        if runner is None:
            raise ValueError("runner must not be None")
        self._runner = runner

    def snapshot(self) -> SystemSnapshot:
        cpu_raw = self._safe_run(["cat", "/proc/cpuinfo"])
        mem_raw = self._safe_run(["cat", "/proc/meminfo"])
        df_raw = self._safe_run(["df", "-k"])
        ip_raw = self._safe_run(["ip", "addr"])
        os_release_raw = self._safe_run(["cat", "/etc/os-release"])
        kernel_raw = self._safe_run(["uname", "-r"])

        cpu = parse_cpuinfo(cpu_raw)
        memory = parse_meminfo(mem_raw)
        disks = parse_df(df_raw)
        networks = parse_ip_addr(ip_raw)
        os_name = parse_os_release(os_release_raw)
        kernel_version = kernel_raw.strip() or "unknown"

        if cpu is None:
            cpu = CPUInfo(cores=0, model_name="unknown")
        if memory is None:
            memory = MemoryInfo(total_mb=0, available_mb=0)

        return SystemSnapshot(
            cpu=cpu,
            memory=memory,
            disks=disks,
            networks=networks,
            os_name=os_name,
            kernel_version=kernel_version,
        )

    def _safe_run(self, cmd: list[str]) -> str:
        try:
            run = getattr(self._runner, "run")
            out = run(cmd, timeout=5)
            if out is None:
                return ""
            return str(out)
        except Exception:
            return ""
