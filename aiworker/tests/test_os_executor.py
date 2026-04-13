import unittest

from aiworker.os.parser import (
    CPUInfo,
    DiskInfo,
    MemoryInfo,
    NetworkInfo,
    parse_cpuinfo,
    parse_df,
    parse_ip_addr,
    parse_meminfo,
    parse_os_release,
)

_CPUINFO_RAW: str = """\
processor\t: 0
vendor_id\t: GenuineIntel
model name\t: Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz
cpu MHz\t\t: 2600.000

processor\t: 1
vendor_id\t: GenuineIntel
model name\t: Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz
cpu MHz\t\t: 2600.000

processor\t: 2
vendor_id\t: GenuineIntel
model name\t: Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz
cpu MHz\t\t: 2600.000

processor\t: 3
vendor_id\t: GenuineIntel
model name\t: Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz
cpu MHz\t\t: 2600.000
"""

_MEMINFO_RAW: str = """\
MemTotal:       16384000 kB
MemFree:         2048000 kB
MemAvailable:    8192000 kB
Buffers:          512000 kB
Cached:          4096000 kB
"""

_DF_RAW: str = """\
Filesystem     1K-blocks     Used Available Use% Mounted on
/dev/sda1      104857600 52428800  52428800  50% /
tmpfs            8192000        0   8192000   0% /dev/shm
devtmpfs         8192000        0   8192000   0% /dev
/dev/sdb1      209715200 104857600 104857600  50% /data
"""

_IP_ADDR_RAW: str = """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    inet 192.168.1.100/24 brd 192.168.1.255 scope global eth0
       valid_lft forever preferred_lft forever
3: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    inet 10.0.0.50/24 brd 10.0.0.255 scope global wlan0
       valid_lft forever preferred_lft forever
"""

_OS_RELEASE_RAW: str = """\
NAME="Ubuntu"
VERSION="24.04 LTS (Noble Numbat)"
ID=ubuntu
PRETTY_NAME="Ubuntu 24.04 LTS"
VERSION_ID="24.04"
"""


class TestParseCPUInfo(unittest.TestCase):

    def test_parses_cores_and_model(self) -> None:
        result: CPUInfo = parse_cpuinfo(_CPUINFO_RAW)
        self.assertEqual(result.cores, 4)
        self.assertEqual(result.model_name, "Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz")

    def test_empty_input_returns_fallback(self) -> None:
        result: CPUInfo = parse_cpuinfo("")
        self.assertEqual(result.cores, 0)
        self.assertEqual(result.model_name, "unknown")

    def test_garbage_input_returns_fallback(self) -> None:
        result: CPUInfo = parse_cpuinfo("nothing useful here\nmore junk")
        self.assertEqual(result.cores, 0)
        self.assertEqual(result.model_name, "unknown")

    def test_deterministic(self) -> None:
        first: CPUInfo = parse_cpuinfo(_CPUINFO_RAW)
        second: CPUInfo = parse_cpuinfo(_CPUINFO_RAW)
        self.assertEqual(first, second)

    def test_frozen(self) -> None:
        result: CPUInfo = parse_cpuinfo(_CPUINFO_RAW)
        with self.assertRaises(AttributeError):
            result.cores = 99  # type: ignore[misc]


class TestParseMeminfo(unittest.TestCase):

    def test_parses_total_and_available(self) -> None:
        result: MemoryInfo = parse_meminfo(_MEMINFO_RAW)
        self.assertEqual(result.total_mb, 16384000 // 1024)
        self.assertEqual(result.available_mb, 8192000 // 1024)

    def test_empty_input_returns_zeros(self) -> None:
        result: MemoryInfo = parse_meminfo("")
        self.assertEqual(result.total_mb, 0)
        self.assertEqual(result.available_mb, 0)

    def test_missing_available_returns_zero(self) -> None:
        result: MemoryInfo = parse_meminfo("MemTotal:       16384000 kB\n")
        self.assertEqual(result.total_mb, 16384000 // 1024)
        self.assertEqual(result.available_mb, 0)

    def test_deterministic(self) -> None:
        self.assertEqual(parse_meminfo(_MEMINFO_RAW), parse_meminfo(_MEMINFO_RAW))


class TestParseDf(unittest.TestCase):

    def test_parses_disks_ignoring_tmpfs(self) -> None:
        results: list[DiskInfo] = parse_df(_DF_RAW)
        self.assertEqual(len(results), 2)
        mount_points: list[str] = [d.mount_point for d in results]
        self.assertIn("/", mount_points)
        self.assertIn("/data", mount_points)

    def test_sorted_by_mount_point(self) -> None:
        results: list[DiskInfo] = parse_df(_DF_RAW)
        mounts: list[str] = [d.mount_point for d in results]
        self.assertEqual(mounts, sorted(mounts))

    def test_kb_to_gb_conversion(self) -> None:
        results: list[DiskInfo] = parse_df(_DF_RAW)
        root: DiskInfo = next(d for d in results if d.mount_point == "/")
        self.assertEqual(root.total_gb, 104857600 // (1024 * 1024))

    def test_used_percent_parsed(self) -> None:
        results: list[DiskInfo] = parse_df(_DF_RAW)
        root: DiskInfo = next(d for d in results if d.mount_point == "/")
        self.assertAlmostEqual(root.used_percent, 50.0)

    def test_empty_input(self) -> None:
        self.assertEqual(parse_df(""), [])

    def test_header_only(self) -> None:
        self.assertEqual(
            parse_df("Filesystem     1K-blocks  Used Available Use% Mounted on\n"),
            [],
        )

    def test_deterministic(self) -> None:
        self.assertEqual(parse_df(_DF_RAW), parse_df(_DF_RAW))


class TestParseIpAddr(unittest.TestCase):

    def test_extracts_ipv4_ignoring_loopback(self) -> None:
        results: list[NetworkInfo] = parse_ip_addr(_IP_ADDR_RAW)
        self.assertEqual(len(results), 2)
        ips: list[str] = [n.ip_address for n in results]
        self.assertNotIn("127.0.0.1", ips)
        self.assertIn("192.168.1.100", ips)
        self.assertIn("10.0.0.50", ips)

    def test_sorted_by_interface(self) -> None:
        results: list[NetworkInfo] = parse_ip_addr(_IP_ADDR_RAW)
        ifaces: list[str] = [n.interface for n in results]
        self.assertEqual(ifaces, sorted(ifaces))

    def test_empty_input(self) -> None:
        self.assertEqual(parse_ip_addr(""), [])

    def test_deterministic(self) -> None:
        self.assertEqual(parse_ip_addr(_IP_ADDR_RAW), parse_ip_addr(_IP_ADDR_RAW))


class TestParseOsRelease(unittest.TestCase):

    def test_extracts_pretty_name(self) -> None:
        result: str = parse_os_release(_OS_RELEASE_RAW)
        self.assertEqual(result, "Ubuntu 24.04 LTS")

    def test_empty_returns_unknown(self) -> None:
        self.assertEqual(parse_os_release(""), "unknown")

    def test_missing_pretty_name_returns_unknown(self) -> None:
        self.assertEqual(parse_os_release("NAME=Ubuntu\nVERSION=24\n"), "unknown")

    def test_single_quoted_value(self) -> None:
        self.assertEqual(
            parse_os_release("PRETTY_NAME='Fedora 40'\n"),
            "Fedora 40",
        )

    def test_deterministic(self) -> None:
        self.assertEqual(
            parse_os_release(_OS_RELEASE_RAW),
            parse_os_release(_OS_RELEASE_RAW),
        )


if __name__ == "__main__":
    unittest.main()
