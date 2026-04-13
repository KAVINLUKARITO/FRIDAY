import unittest

from aiworker.os.introspection import SystemIntrospector
from aiworker.os.parser import (
    CPUInfo,
    DiskInfo,
    MemoryInfo,
    NetworkInfo,
    SystemSnapshot,
)

_CPUINFO: str = """\
processor\t: 0
model name\t: TestCPU

processor\t: 1
model name\t: TestCPU
"""

_MEMINFO: str = """\
MemTotal:       8192000 kB
MemFree:        1024000 kB
MemAvailable:   4096000 kB
"""

_DF: str = """\
Filesystem     1K-blocks     Used Available Use% Mounted on
/dev/sda1      104857600 52428800  52428800  50% /
tmpfs            8192000        0   8192000   0% /dev/shm
"""

_IP_ADDR: str = """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536
    inet 127.0.0.1/8 scope host lo
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    inet 10.0.0.5/24 brd 10.0.0.255 scope global eth0
"""

_OS_RELEASE: str = 'PRETTY_NAME="TestOS 1.0"\nNAME="TestOS"\n'

_UNAME: str = "6.5.0-generic\n"

_COMMAND_MAP: dict[str, str] = {
    "cat /proc/cpuinfo": _CPUINFO,
    "cat /proc/meminfo": _MEMINFO,
    "df -k": _DF,
    "ip addr": _IP_ADDR,
    "cat /etc/os-release": _OS_RELEASE,
    "uname -r": _UNAME,
}


class StubRunner:
    def __init__(self, responses: dict[str, str]) -> None:
        self._responses: dict[str, str] = responses
        self.calls: list[list[str]] = []

    def run(self, cmd: list[str], timeout: int = 5) -> str:
        self.calls.append(cmd)
        key: str = " ".join(cmd)
        if key in self._responses:
            return self._responses[key]
        raise RuntimeError(f"No stub for {key}")


class FailingRunner:
    def run(self, cmd: list[str], timeout: int = 5) -> str:
        raise RuntimeError("command failed")


class TestIntrospectorHappyPath(unittest.TestCase):

    def test_snapshot_returns_valid_object(self) -> None:
        runner: StubRunner = StubRunner(_COMMAND_MAP)
        introspector: SystemIntrospector = SystemIntrospector(runner)
        snap: SystemSnapshot = introspector.snapshot()

        self.assertIsInstance(snap, SystemSnapshot)
        self.assertEqual(snap.cpu.cores, 2)
        self.assertEqual(snap.cpu.model_name, "TestCPU")
        self.assertEqual(snap.memory.total_mb, 8192000 // 1024)
        self.assertEqual(snap.memory.available_mb, 4096000 // 1024)
        self.assertEqual(len(snap.disks), 1)
        self.assertEqual(snap.disks[0].mount_point, "/")
        self.assertEqual(len(snap.networks), 1)
        self.assertEqual(snap.networks[0].ip_address, "10.0.0.5")
        self.assertEqual(snap.os_name, "TestOS 1.0")
        self.assertEqual(snap.kernel_version, "6.5.0-generic")

    def test_all_commands_executed(self) -> None:
        runner: StubRunner = StubRunner(_COMMAND_MAP)
        introspector: SystemIntrospector = SystemIntrospector(runner)
        introspector.snapshot()
        self.assertEqual(len(runner.calls), 6)

    def test_deterministic(self) -> None:
        runner1: StubRunner = StubRunner(_COMMAND_MAP)
        runner2: StubRunner = StubRunner(_COMMAND_MAP)
        snap1: SystemSnapshot = SystemIntrospector(runner1).snapshot()
        snap2: SystemSnapshot = SystemIntrospector(runner2).snapshot()
        self.assertEqual(snap1, snap2)


class TestIntrospectorFailures(unittest.TestCase):

    def test_all_commands_fail_returns_safe_defaults(self) -> None:
        runner: FailingRunner = FailingRunner()
        introspector: SystemIntrospector = SystemIntrospector(runner)
        snap: SystemSnapshot = introspector.snapshot()

        self.assertIsInstance(snap, SystemSnapshot)
        self.assertEqual(snap.cpu, CPUInfo(cores=0, model_name="unknown"))
        self.assertEqual(snap.memory, MemoryInfo(total_mb=0, available_mb=0))
        self.assertEqual(snap.disks, [])
        self.assertEqual(snap.networks, [])
        self.assertEqual(snap.os_name, "unknown")
        self.assertEqual(snap.kernel_version, "unknown")

    def test_partial_failure_still_returns_snapshot(self) -> None:
        partial: dict[str, str] = {
            "cat /proc/cpuinfo": _CPUINFO,
            "cat /proc/meminfo": _MEMINFO,
        }
        runner: StubRunner = StubRunner(partial)
        introspector: SystemIntrospector = SystemIntrospector(runner)
        snap: SystemSnapshot = introspector.snapshot()

        self.assertEqual(snap.cpu.cores, 2)
        self.assertEqual(snap.memory.total_mb, 8192000 // 1024)
        self.assertEqual(snap.disks, [])
        self.assertEqual(snap.networks, [])
        self.assertEqual(snap.os_name, "unknown")
        self.assertEqual(snap.kernel_version, "unknown")


class TestIntrospectorValidation(unittest.TestCase):

    def test_none_runner_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SystemIntrospector(None)  # type: ignore[arg-type]

    def test_no_none_values_in_snapshot(self) -> None:
        runner: FailingRunner = FailingRunner()
        snap: SystemSnapshot = SystemIntrospector(runner).snapshot()
        for field_name in ("cpu", "memory", "disks", "networks", "os_name", "kernel_version"):
            self.assertIsNotNone(getattr(snap, field_name))


if __name__ == "__main__":
    unittest.main()
