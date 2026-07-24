#!/usr/bin/env python3
"""
k6-flamegraph: drive a coolwsd workload with a k6 test and capture a perf
flamegraph of the kit activity. Python port of the bash script.

CLI flags override environment variables override built-in defaults. Run
with --help for the full list.

Outputs (under --out-dir): coolwsd.log, wopi.log, k6.log, perf.log,
perf.data, flamegraph.svg, and per-process instruction
counts in perf-stat-coolwsd.csv / perf-stat-kit.csv (coolwsd+forkit vs the
document kit; the run summary prints both plus a combined total). A
machine-readable metrics.json collects the per-process instructions, cycles,
IPC and CPU time, plus a resident-memory time series and peak (RSS and, when
readable, PSS) for coolwsd and the kit, for plotting across runs.
"""

import argparse
import json
import os
import re
import shutil
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from pylib.perfutils import (
    MemorySampler,
    collect_perf,
    collect_workload,
    coolwsd_cgroup,
    document_kit_pids,
    flamegraph_sample_count,
    pgrep,
    print_memory,
    print_perf,
    print_workload,
)

SCRIPT_DIR = Path(__file__).resolve().parent


def die(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def need(cmd: str, hint: str) -> None:
    if shutil.which(cmd) is None:
        die(f"missing required command: {cmd}\n{hint}")


def env_default(name: str, default: str) -> str:
    """Read NAME from environment, falling back to default. Empty = default."""
    val = os.environ.get(name)
    return val if val else default


def env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val == "1"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="k6-flamegraph",
        description=(
            "Drive a coolwsd workload with a k6 test and capture a perf "
            "flamegraph of kit activity. Precedence: CLI flags > env vars > "
            "built-in defaults."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "test_script",
        nargs="?",
        default=None,
        help=(
            "k6 test script, relative to this script's directory "
            "(default dist/cool-load-document-test.js) (env TEST_SCRIPT)"
        ),
    )
    p.add_argument(
        "--coolwsd-dir",
        default=env_default("COOLWSD_DIR", "/home/meven/code/online"),
        help="path to the online checkout (env COOLWSD_DIR)",
    )
    p.add_argument(
        "--coolwsd-url",
        default=env_default("COOLWSD_URL", "https://localhost:9980/"),
        help="URL coolwsd serves at (env COOLWSD_URL)",
    )
    p.add_argument(
        "--host-ip",
        default=os.environ.get("HOST_IP") or None,
        help="host IP reachable from the k6 docker container "
             "(default: auto-detect via `ip route`) (env HOST_IP)",
    )
    p.add_argument(
        "--wopi-port",
        default=env_default("WOPI_PORT", "3000"),
        help="WOPI host port (env WOPI_PORT)",
    )
    p.add_argument(
        "--wopi-scheme",
        choices=("http", "https"),
        default=env_default("WOPI_SCHEME", "https"),
        help="WOPI host scheme; must match coolwsd's "
             "(the demo html rejects http parent + https iframe) (env WOPI_SCHEME)",
    )
    p.add_argument(
        "--wopi-key",
        default=os.environ.get("WOPI_SSL_KEY") or None,
        help="TLS key for the WOPI host (default $COOLWSD_DIR/etc/key.pem) "
             "(env WOPI_SSL_KEY)",
    )
    p.add_argument(
        "--wopi-crt",
        default=os.environ.get("WOPI_SSL_CRT") or None,
        help="TLS cert (default $COOLWSD_DIR/etc/cert.pem) (env WOPI_SSL_CRT)",
    )
    p.add_argument(
        "--out-dir",
        default=env_default("OUT_DIR", "profile-out"),
        help="output directory (env OUT_DIR)",
    )
    p.add_argument(
        "--perf-freq",
        type=int,
        default=int(env_default("PERF_FREQ", "200")),
        help="perf sampling frequency Hz (env PERF_FREQ)",
    )
    p.add_argument(
        "--perf-event",
        default=env_default("PERF_EVENT", "cycles"),
        help="perf sampling event (env PERF_EVENT). On a hybrid P/E-core CPU "
             "the default 'cycles' can fail to open for perf record; try "
             "'cpu_core/cycles/' or 'cpu_atom/cycles/'",
    )
    p.add_argument(
        "--cgroup",
        action=argparse.BooleanOptionalAction,
        default=env_bool("COOL_K6_CGROUP", False),
        help="launch coolwsd in a dedicated cgroup (systemd --scope) and record "
             "with perf -a -G <cgroup> --namespaces. Captures every kit the "
             "moment it forks (cgroup membership is inherited across fork and "
             "survives the jail namespaces), no pid-chasing. Needs systemd-run "
             "and lowers perf_event_paranoid to 0. Falls back to --pid targeting "
             "if unavailable. (env COOL_K6_CGROUP=1/0)",
    )
    p.add_argument(
        "--stop-coolwsd",
        action=argparse.BooleanOptionalAction,
        default=env_bool("STOP_COOLWSD", True),
        help="when coolwsd was started by this script, stop it at "
             "the end of the run so the next invocation starts a "
             "fresh process with the env it inherits. Pass "
             "--no-stop-coolwsd to keep the started coolwsd alive "
             "for reuse across runs. Has no effect when coolwsd was "
             "already running before this invocation. "
             "(env STOP_COOLWSD=1/0)",
    )
    return p.parse_args()


def detect_host_ip() -> str | None:
    try:
        out = subprocess.run(
            ["ip", "route", "get", "1.1.1.1"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if "src" in parts:
            i = parts.index("src")
            if i + 1 < len(parts):
                return parts[i + 1]
    return None


# coolwsd and the WOPI host use self-signed certs in dev, so reachability
# checks skip certificate verification (the equivalent of curl -k).
_INSECURE_SSL = ssl.create_default_context()
_INSECURE_SSL.check_hostname = False
_INSECURE_SSL.verify_mode = ssl.CERT_NONE


def http_ok(url: str) -> bool:
    """True if url answers over HTTP(S), the way `curl -ks` exits 0. An HTTP
    error status still counts as reachable, since the server did answer."""
    try:
        urllib.request.urlopen(url, timeout=15, context=_INSECURE_SSL).close()
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def wait_for(desc: str, max_seconds: int, check) -> None:
    for _ in range(max_seconds):
        try:
            if check():
                return
        except Exception:
            pass
        time.sleep(1)
    die(f"timed out waiting for {desc}")


def sudo_needs_password() -> bool:
    """True if a sudo command would prompt for a password (no cached or
    passwordless credentials)."""
    try:
        return subprocess.run(
            ["sudo", "-n", "true"], capture_output=True, timeout=5,
        ).returncode != 0
    except Exception:
        return True


def _read_int(path: str, default: int) -> int:
    try:
        return int(Path(path).read_text().strip())
    except Exception:
        return default


def perf_can_bypass_paranoid() -> bool:
    """True if perf can record regardless of perf_event_paranoid: running as
    root, or the perf binary carries CAP_PERFMON / CAP_SYS_ADMIN. When true we
    skip lowering the kernel knob (and the sudo prompt that needs)."""
    if os.geteuid() == 0:
        return True
    perf = shutil.which("perf")
    if not perf:
        return False
    try:
        out = subprocess.run(["getcap", os.path.realpath(perf)],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True).stdout.lower()
    except FileNotFoundError:
        return False
    return "cap_perfmon" in out or "cap_sys_admin" in out


def prepare_perf(system_wide: bool = False) -> tuple[list[str], list[str], str]:
    """Make perf usable for recording our own coolwsd processes, prompting for
    sudo only when a kernel knob actually has to change.

    Returns (sudo_perf, perf_mmap, mmap_desc):
      - sudo_perf : command prefix for perf (empty; recording our own
                    processes needs no elevation once paranoid <= 2).
      - perf_mmap : the ["-m", "<N>M"] mmap-ring option for `perf record` ([]
                    if the cap is too small for even 1 MB).
      - mmap_desc : human-readable mmap size, for log messages.
    """
    paranoid_path = "/proc/sys/kernel/perf_event_paranoid"
    mlock_path = "/proc/sys/kernel/perf_event_mlock_kb"

    # Per-process (--pid) recording of our own coolwsd works unprivileged at
    # perf_event_paranoid <= 2. System-wide / cgroup capture (-a, -G) uses
    # CPU-wide events, which need <= 0. If the knob is too high, lower it once
    # with sudo (prompting for the password); the recording then runs
    # unprivileged.
    if system_wide:
        max_paranoid, target = 0, 0
        why = "system-wide / cgroup capture"
    else:
        max_paranoid, target = 2, 1
        why = "profiling"
    paranoid = _read_int(paranoid_path, 4)
    if perf_can_bypass_paranoid():
        # perf has CAP_PERFMON (or we are root): no knob change, no sudo prompt.
        # This is the fool-proof setup - grant it once with:
        #   sudo setcap cap_perfmon,cap_sys_ptrace+ep "$(command -v perf)"
        print(f"perf can record without lowering perf_event_paranoid "
              f"(currently {paranoid}): CAP_PERFMON on perf, or running as root.")
    elif paranoid > max_paranoid:
        print(f"kernel.perf_event_paranoid={paranoid} is too restrictive for {why}; "
              f"lowering it to {target}.")
        if sudo_needs_password():
            print("You may be prompted for your sudo password. To avoid this, "
                  "grant perf CAP_PERFMON once: "
                  "sudo setcap cap_perfmon,cap_sys_ptrace+ep \"$(command -v perf)\"")
        subprocess.run(f"echo {target} | sudo tee {paranoid_path}", shell=True)
        paranoid = _read_int(paranoid_path, 4)
        if paranoid > max_paranoid:
            die(f"perf_event_paranoid is still {paranoid}; cannot record. Lower it "
                f"manually (echo {target} | sudo tee {paranoid_path}) or grant "
                f"perf CAP_PERFMON (setcap cap_perfmon,cap_sys_ptrace+ep perf).")
    # Recording at this paranoid level needs no per-command elevation.
    sudo_perf: list[str] = []

    # dwarf call-graph copies a large stack per sample, which overflows the
    # unprivileged perf ring buffer (perf_event_mlock_kb, 516 KB by default)
    # and drops almost every sample. Raise the cap if it is too small (prompts
    # for sudo), then size perf's mmap ring to fit under it.
    MLOCK_MIN_KB = 32768
    mlock_kb = _read_int(mlock_path, 0)
    if mlock_kb < MLOCK_MIN_KB:
        print(f"kernel.perf_event_mlock_kb={mlock_kb} is too small for dwarf "
              f"call-graph capture; raising it to {MLOCK_MIN_KB}.")
        if sudo_needs_password():
            print("You may be prompted for your sudo password.")
        subprocess.run(f"echo {MLOCK_MIN_KB} | sudo tee {mlock_path}", shell=True)
        mlock_kb = _read_int(mlock_path, 0)

    # Largest power-of-two-MB mmap ring that fits under the per-cpu cap (perf
    # requires -m to be a power-of-two page count; leave a page of headroom).
    mmap_mb = 0
    mb = 1
    while mb * 1024 <= mlock_kb - 4:
        mmap_mb = mb
        mb *= 2
    perf_mmap = ["-m", f"{mmap_mb}M"] if mmap_mb >= 1 else []
    mmap_desc = f"{mmap_mb}M" if mmap_mb >= 1 else "default"
    if mlock_kb < MLOCK_MIN_KB:
        print(f"warning: perf_event_mlock_kb is only {mlock_kb} KB; dwarf capture "
              f"may still drop samples (mmap {mmap_desc})", file=sys.stderr)

    return sudo_perf, perf_mmap, mmap_desc


def _perf_event_captures(event: str, perf_freq: str, sudo_perf: list[str],
                         perf_mmap: list[str], out_dir: Path) -> bool:
    """Record a short busy workload and report whether perf actually captured
    samples with this event. Catches a hybrid P/E-core PMU that silently opens
    no counter for `perf record` (while `perf stat` still counts)."""
    tmp = out_dir / ".perf-selftest.data"
    for f in (tmp, Path(str(tmp) + ".old")):
        try:
            f.unlink()
        except FileNotFoundError:
            pass
    # `yes` burns CPU; timeout bounds it; >/dev/null keeps its output off perf's
    # pipe. Same dwarf + mmap options as the real capture, so the test exercises
    # the real path.
    proc = subprocess.run(
        [*sudo_perf, "perf", "record", f"-F{perf_freq}", "-e", event,
         "--call-graph", "dwarf,32768", *perf_mmap, "-o", str(tmp),
         "--", "sh", "-c", "timeout 0.5 yes >/dev/null 2>&1"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    m = re.search(r"\((\d+)\s+samples\)", proc.stdout or "")
    captured = bool(m and int(m.group(1)) > 0)
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
    return captured


def pick_perf_event(preferred: str, perf_freq: str, sudo_perf: list[str],
                    perf_mmap: list[str], out_dir: Path) -> str | None:
    """First sampling event that actually captures on this CPU: the preferred
    one, then hybrid P/E-core variants, then task-clock (a software event that
    always works). None if perf can capture nothing at all."""
    candidates = [preferred, "cpu_core/cycles/", "cpu_atom/cycles/", "task-clock"]
    tried: list[str] = []
    for ev in candidates:
        if ev in tried:
            continue
        tried.append(ev)
        if _perf_event_captures(ev, perf_freq, sudo_perf, perf_mmap, out_dir):
            if ev != preferred:
                print(f"perf self-test: '{preferred}' captured no samples on this "
                      f"CPU; falling back to '{ev}'.")
            else:
                print(f"perf self-test: event '{ev}' captures samples - good.")
            return ev
        print(f"perf self-test: '{ev}' captured nothing, trying next ...")
    return None


def main() -> int:
    args = parse_args()
    start_ts = time.monotonic()

    # Only the k6 runner is supported. Kept as a named constant so the
    # summary strings and the reachability guard read clearly, and so the
    # puppeteer runner can be restored later if needed.
    runner = "k6"
    test_script = args.test_script or "dist/cool-load-document-test.js"

    coolwsd_dir = Path(args.coolwsd_dir)
    coolwsd_url = args.coolwsd_url
    wopi_port = args.wopi_port
    out_dir = Path(args.out_dir)
    perf_freq = str(args.perf_freq)
    perf_event = args.perf_event

    host_ip = args.host_ip or detect_host_ip()
    if not host_ip:
        die("could not auto-detect HOST_IP; pass --host-ip <your host IP>")

    need("perf", "Install perf (Arch: sudo pacman -S perf, Fedora: sudo dnf install perf)")
    need("stackcollapse-perf.pl", "Install FlameGraph (Arch AUR: yay -S flamegraph; Fedora: sudo dnf install flamegraph; or git clone https://github.com/brendangregg/FlameGraph and add to PATH)")
    need("flamegraph.pl", "Install FlameGraph (same as above)")
    need("docker", "k6-wrap uses docker; install and enable the docker daemon")
    need("pgrep", "pgrep should be in any base install")

    if not coolwsd_dir.is_dir():
        die(f"coolwsd directory not found: {coolwsd_dir}")
    test_path = SCRIPT_DIR / test_script
    if not test_path.is_file():
        die(f"k6 test script not found: {test_path}\n"
            f"(did you run `npm run build` in {SCRIPT_DIR}?)")

    cgroup_mode = bool(args.cgroup)
    if cgroup_mode and shutil.which("systemd-run") is None:
        print("warning: --cgroup needs systemd-run, which is missing; "
              "using --pid targeting instead", file=sys.stderr)
        cgroup_mode = False
    if cgroup_mode and not Path("/sys/fs/cgroup/cgroup.controllers").exists():
        print("warning: --cgroup needs cgroup v2 (unified) mounted at "
              "/sys/fs/cgroup; using --pid targeting instead", file=sys.stderr)
        cgroup_mode = False

    sudo_perf, perf_mmap, mmap_desc = prepare_perf(system_wide=cgroup_mode)

    out_dir.mkdir(parents=True, exist_ok=True)

    # Preflight: confirm perf can actually capture with the chosen event and
    # auto-fall-back if not (hybrid P/E-core CPUs silently record nothing on the
    # default 'cycles'). Doing this now - before starting coolwsd and running
    # the whole workload - turns a wasted 2-minute run into a 2-second check.
    print("perf self-test: checking the sampling event captures on this CPU ...")
    chosen = pick_perf_event(perf_event, perf_freq, sudo_perf, perf_mmap, out_dir)
    if chosen is None:
        die("perf captured no samples in a self-test with any of "
            f"{perf_event}, cpu_core/cycles/, cpu_atom/cycles/, task-clock. "
            "perf recording is not working on this machine - check "
            "'perf record -e cycles -F99 -- sh -c \"timeout 1 yes >/dev/null\"' "
            "and perf_event_paranoid.")
    perf_event = chosen

    scope_unit: str | None = None  # transient systemd scope, if we launch one

    coolwsd_proc: subprocess.Popen | None = None
    wopi_proc: subprocess.Popen | None = None
    perf_proc: subprocess.Popen | None = None
    perf_stat_procs: list[subprocess.Popen] = []
    runner_proc: subprocess.Popen | None = None
    started_coolwsd = False
    started_wopi = False

    def sigint_wait(proc: subprocess.Popen | None, timeout: int) -> None:
        """Stop a still-running perf process with SIGINT and wait for it to
        flush and exit, ignoring a wait timeout. perf may be running under
        sudo, so the signal is sent the same way."""
        if not proc or proc.poll() is not None:
            return
        subprocess.run([*sudo_perf, "kill", "-SIGINT", str(proc.pid)],
                       stderr=subprocess.DEVNULL)
        try:
            proc.wait(timeout=timeout)
        except Exception:
            pass

    def cleanup() -> None:
        nonlocal perf_proc, perf_stat_procs, runner_proc, wopi_proc, coolwsd_proc
        sigint_wait(perf_proc, 10)
        for sp in perf_stat_procs:
            sigint_wait(sp, 10)
        if runner_proc and runner_proc.poll() is None:
            runner_proc.terminate()
            try:
                runner_proc.wait(timeout=10)
            except Exception:
                runner_proc.kill()
        if started_wopi and wopi_proc and wopi_proc.poll() is None:
            wopi_proc.terminate()
            try:
                wopi_proc.wait(timeout=10)
            except Exception:
                wopi_proc.kill()
        if (started_coolwsd and args.stop_coolwsd
                and coolwsd_proc and coolwsd_proc.poll() is None):
            # `make run` forks coolwsd; kill the process group.
            # Default on so a follow-up run with different env (e.g.
            # SAL_KIT_OPTIONS) gets a fresh kit; pass
            # --no-stop-coolwsd to keep it alive between runs.
            try:
                os.killpg(coolwsd_proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                coolwsd_proc.wait(timeout=15)
            except Exception:
                pass
            if scope_unit:
                subprocess.run(["systemctl", "--user", "stop", scope_unit],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def on_signal(*_a):
        cleanup()
        sys.exit(130)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    try:
        # coolwsd
        if http_ok(f"{coolwsd_url}hosting/discovery"):
            print(f"WARNING: coolwsd is already running at {coolwsd_url}; "
                  "attaching to it instead of launching one.", file=sys.stderr)
            print("  It is not controlled by this tool: it may be a multi-kit "
                  "'make run' whose kits spawn and unload during the run, not "
                  "the single stable kit a clean capture needs.", file=sys.stderr)
            print("  For a reliable, symbolised profile, stop it first "
                  "(pkill -f coolwsd) and re-run so this tool launches its own "
                  "single kit.", file=sys.stderr)
            if cgroup_mode:
                print("  cgroup mode: with no dedicated scope, perf -G records "
                      "whatever cgroup it sits in (may include sibling "
                      "processes).", file=sys.stderr)
        else:
            print(f"starting coolwsd from {coolwsd_dir} ...")
            log = (out_dir / "coolwsd.log").open("w")
            cmd = ["setsid", "make", "run-one"]
            if cgroup_mode:
                scope_unit = f"coolperf-{os.getpid()}.scope"
                cmd = ["systemd-run", "--user", "--scope", "--collect",
                       f"--unit={scope_unit}", *cmd]
                print(f"launching coolwsd in cgroup scope {scope_unit} ...")
            coolwsd_proc = subprocess.Popen(
                cmd,
                cwd=str(coolwsd_dir),
                stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            started_coolwsd = True
            wait_for("coolwsd ready", 60,
                     lambda: http_ok(f"{coolwsd_url}hosting/discovery"))

        wopi_scheme = args.wopi_scheme
        wopi_key = args.wopi_key or str(coolwsd_dir / "etc" / "key.pem")
        wopi_crt = args.wopi_crt or str(coolwsd_dir / "etc" / "cert.pem")
        wopi_base = f"{wopi_scheme}://{host_ip}:{wopi_port}"

        # WOPI host
        if http_ok(f"{wopi_base}/wopi/files/1"):
            print(f"WOPI host already running at {wopi_base}/")
        else:
            if wopi_scheme == "https" and (
                not Path(wopi_key).is_file() or not Path(wopi_crt).is_file()
            ):
                die(
                    "missing TLS cert/key for WOPI host:\n"
                    f"  key: {wopi_key}\n  crt: {wopi_crt}\n"
                    "set WOPI_SSL_KEY / WOPI_SSL_CRT (or WOPI_SCHEME=http) and retry."
                )
            print(f"starting WOPI host on {wopi_base}/ ...")
            log = (out_dir / "wopi.log").open("w")
            wopi_proc = subprocess.Popen(
                ["npm", "run", "server"],
                cwd=str(SCRIPT_DIR),
                env={**os.environ,
                     "PORT": wopi_port,
                     "SSL_KEY_FILE": wopi_key,
                     "SSL_CRT_FILE": wopi_crt,
                     "NODE_TLS_REJECT_UNAUTHORIZED": "0"},
                stdout=log, stderr=subprocess.STDOUT,
            )
            started_wopi = True
            wait_for("WOPI host ready", 30,
                     lambda: http_ok(f"{wopi_base}/wopi/files/1"))

        perf_data = out_dir / "perf.data"

        def build_runner():
            # k6 runs inside docker; translate localhost -> HOST_IP so the
            # container reaches host coolwsd.
            url = re.sub(r"//(localhost|127\.0\.0\.1)([:/])",
                         f"//{host_ip}\\2", coolwsd_url)
            print(f"starting k6 test: {test_script} (WOPI_URL={url}) ...")
            env = {**os.environ, "WOPI_URL": url, "WOPI_HOST": f"{wopi_base}/",
                   "NODE_TLS_REJECT_UNAUTHORIZED": "0"}
            cmd = ["./k6-run", test_script]
            blog = (out_dir / "browser.log").open("w")
            return subprocess.Popen(cmd, cwd=str(SCRIPT_DIR), env=env,
                                    stdout=blog, stderr=subprocess.STDOUT)

        def start_perf(target, extra=()):
            try:
                perf_data.unlink()
            except FileNotFoundError:
                pass
            print(f"starting perf record (F={perf_freq}, event {perf_event}, "
                  f"mmap {mmap_desc}) ...")
            plog = (out_dir / "perf.log").open("w")
            # Name the event explicitly (and before any --cgroup in target): on
            # a hybrid P/E-core CPU perf record's implicit default event can
            # fail to open and capture nothing, while perf stat still counts.
            proc = subprocess.Popen(
                [*sudo_perf, "perf", "record", f"-F{perf_freq}", "-e", perf_event,
                 "--call-graph", "dwarf,32768", *perf_mmap, *extra, *target,
                 "-o", str(perf_data)],
                stdout=plog, stderr=subprocess.STDOUT)
            for _ in range(10):  # wait until perf is actually writing
                if perf_data.exists() and perf_data.stat().st_size > 0:
                    break
                time.sleep(0.5)
            if not perf_data.exists() or perf_data.stat().st_size == 0:
                sys.stderr.write("perf failed to start recording; perf.log says:\n")
                sys.stderr.write((out_dir / "perf.log").read_text())
                return None
            return proc

        def start_perf_stat_group(label: str, pids: list[str]):
            """Count instructions/cycles for one process group (its own CSV).

            The groups are disjoint pid sets (coolwsd+forkit vs the document
            kit), so no task is counted twice - that keeps each event on its
            own hardware counter instead of multiplexing (which would scale
            the numbers). Output: perf-stat-<label>.csv."""
            if not pids:
                print(f"skipping perf stat ({label}): no pids to attach to")
                return None
            csv_out = out_dir / f"perf-stat-{label}.csv"
            try:
                csv_out.unlink()
            except FileNotFoundError:
                pass
            print(f"starting perf stat ({label}: pid {','.join(pids)}) ...")
            slog = (out_dir / f"perf-stat-{label}.log").open("w")
            # LC_ALL=C forces a period decimal separator so the -x , CSV holds.
            return subprocess.Popen(
                [*sudo_perf, "perf", "stat", "-e", "instructions,cycles,task-clock",
                 "-x", ",", "--pid", ",".join(pids), "-o", str(csv_out)],
                env={**os.environ, "LC_ALL": "C", "LANG": "C"},
                stdout=slog, stderr=subprocess.STDOUT)

        def start_perf_stat_groups() -> list[subprocess.Popen]:
            """Start one perf stat per process group. coolwsd/forkit are the
            WSD side; kitbroker_* is the document kit (LibreOfficeKit work).
            Uses explicit pids regardless of how perf record targets, so it
            works in both --pid and --cgroup modes."""
            wsd_pids = sorted(set(pgrep(["-x", "coolwsd"]) + pgrep(["-x", "forkit"])))
            groups = [("coolwsd", wsd_pids), ("kit", kit_pids)]
            return [p for label, pids in groups
                    if (p := start_perf_stat_group(label, pids)) is not None]

        # The k6 container dials the host_ip-rewritten coolwsd URL, not
        # localhost. Verify that exact URL is reachable *before* running the
        # whole workload: coolwsd's readiness was checked on localhost, but it
        # may listen only on loopback, or --find-free-port may have bound a
        # different port - either way the container would get "connection
        # refused" and the run would waste minutes for nothing.
        dialed = re.sub(r"//(localhost|127\.0\.0\.1)([:/])",
                        f"//{host_ip}\\2", coolwsd_url)
        if not http_ok(f"{dialed}hosting/discovery"):
            die(f"coolwsd is up on localhost but not reachable at {dialed} "
                "- the address the k6 container will dial. It is likely "
                "listening only on loopback, or --find-free-port bound a "
                "different port. Check: ss -ltnp | grep -E ':(9980|998[0-9])'. "
                "The container reaches the host via its LAN IP, so coolwsd "
                "must listen on 0.0.0.0 (or that IP) on the expected port.")
        print(f"reachability: k6 will dial {dialed} (verified reachable).")

        # Both modes profile the live document kit (comm kitbroker_<hash>; its
        # lokit_runloop thread does the LO work), but they differ in ordering:
        #
        #  - cgroup mode: coolwsd runs inside a systemd --scope, so the scope's
        #    cgroup is known as soon as coolwsd is up. The kit is forked from
        #    coolwsd and inherits that same cgroup (membership follows fork and
        #    survives the kit's namespace unshare), so perf can attach to the
        #    cgroup BEFORE the workload runs. Opening the document then happens
        #    while perf is already recording, which captures the kit's initial
        #    import and first render, not just the steady-state scroll.
        #
        #  - pid mode: perf --pid cannot target a process that does not exist
        #    yet, so the workload must start first; we wait for the kit to spawn
        #    before attaching (and its pid is what resolves the jailed symbols).
        kit_pids: list[str] = []

        def launch_and_wait_for_kit() -> tuple[float, subprocess.Popen, list[str]]:
            start = time.monotonic()
            proc = build_runner()
            print("waiting for the document kit (kitbroker_*) to spawn ...")
            pids: list[str] = []
            for i in range(30):
                pids = document_kit_pids()
                if pids:
                    print(f"document kit pid(s): {','.join(pids)}")
                    break
                if proc.poll() is not None:
                    break  # workload exited before a kit showed up
                # Stop waiting early if coolwsd itself has gone away (crash /
                # assert / OOM kill) - no kit can spawn from a dead coolwsd.
                if i % 3 == 2 and not http_ok(f"{coolwsd_url}hosting/discovery"):
                    print("coolwsd became unreachable before a kit spawned",
                          file=sys.stderr)
                    break
                time.sleep(1)
            if not pids:
                print("warning: no document kit (kitbroker_*) appeared; the doc "
                      "may not have opened", file=sys.stderr)
            return start, proc, pids

        if cgroup_mode:
            # The kit will join coolwsd's scope cgroup on fork, so resolve it now
            # from the already-running coolwsd; fall back to pid mode if it
            # cannot be read.
            cgpath = coolwsd_cgroup()
            if not cgpath:
                print("warning: could not resolve coolwsd's cgroup; falling back "
                      "to --pid targeting", file=sys.stderr)
                cgroup_mode = False

        if cgroup_mode:
            target = ["-a", "--cgroup", cgpath]
            print(f"perf will record cgroup {cgpath} (system-wide, cgroup-filtered)")
            # start_perf names the event (before --cgroup, as perf requires) and
            # --namespaces resolves symbols across the kit's namespaces.
            perf_proc = start_perf(target, extra=["--namespaces"])
            if perf_proc is None:
                return 1
            # perf is already recording the cgroup; now open the document so the
            # kit is captured from its first instruction. (perf stat is per-pid
            # and starts below, once the kit pid is known.)
            runner_start, runner_proc, kit_pids = launch_and_wait_for_kit()
        else:
            # perf --pid needs the kit to exist first: open the document, wait
            # for the kit, then attach.
            runner_start, runner_proc, kit_pids = launch_and_wait_for_kit()
            cool_pids = sorted(set(
                pgrep(["-x", "coolwsd"]) + pgrep(["-x", "forkit"]) + kit_pids))
            if not cool_pids:
                print("no coolwsd processes found; perf will record system-wide (-a)")
                target = ["-a"]
            else:
                print(f"perf will record PIDs: {','.join(cool_pids)}")
                target = ["--pid", ",".join(cool_pids)]
            perf_proc = start_perf(target)
            if perf_proc is None:
                return 1

        # Fail fast if the document never opened: no kit spawned and coolwsd is
        # no longer reachable means it died during startup or the first load
        # (crash, assert, or an OOM kill under load). Recording on would only
        # produce an empty perf.data, so stop now and point at the log. cleanup()
        # in the finally block tears down the perf we just started.
        if not kit_pids and not http_ok(f"{coolwsd_url}hosting/discovery"):
            print("ERROR: coolwsd is no longer reachable and no document kit "
                  "ever spawned - it died during the run, so there is nothing "
                  "to profile (perf.data would be empty). See "
                  f"{out_dir}/coolwsd.log for the cause (crash / assert / OOM). "
                  "Under a heavy or concurrent load a --singlekit coolwsd (what "
                  "'make run-one' starts) is a common culprit; profile a single "
                  "document, or run the load test without perf.", file=sys.stderr)
            return 1

        # Count instructions/cycles per process group now that the kit pid is
        # known: one perf stat for coolwsd+forkit, one for the document kit,
        # written to perf-stat-coolwsd.csv / perf-stat-kit.csv.
        perf_stat_procs = start_perf_stat_groups()

        print(f"waiting for {runner} to finish ...")
        # In pid mode perf only follows the kit(s) that existed at attach time.
        # If a targeted kit is unloaded mid-run (a workload that churns
        # documents, or a multi-kit coolwsd), perf loses its target and the
        # capture ends up empty or partial - warn loudly rather than fail
        # silently and hand back an unreadable perf.data.
        monitor_kits = (not cgroup_mode) and bool(kit_pids)
        warned_kit_gone = False

        # Sample resident memory every couple of seconds while the workload
        # runs, so the JSON carries a time series and a true concurrent peak.
        # coolwsd's and forkit's pids are stable for the run, so resolve once.
        mem_wsd_pids = sorted(set(pgrep(["-x", "coolwsd"]) + pgrep(["-x", "forkit"])))
        mem_sampler = MemorySampler({"coolwsd": mem_wsd_pids, "kit": kit_pids})

        mem_sampler.sample()
        while True:
            try:
                runner_rc = runner_proc.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                pass
            mem_sampler.sample()
            if monitor_kits and not warned_kit_gone:
                alive = [p for p in kit_pids if Path(f"/proc/{p}").exists()]
                if not alive:
                    warned_kit_gone = True
                    print("WARNING: the profiled document kit(s) "
                          f"({','.join(kit_pids)}) exited while perf was still "
                          "recording. pid mode follows only the kit that existed "
                          "at attach time, so this capture will be empty or "
                          "partial. Profile a single stable document, or re-run "
                          "with no coolwsd running so a controlled single kit is "
                          "launched.", file=sys.stderr)
        runner_proc = None
        runner_elapsed = int(time.monotonic() - runner_start)
        print(f"{runner} elapsed: {runner_elapsed}s")

        # let perf capture a tail then stop it gracefully
        time.sleep(2)
        print("stopping perf ...")
        print("perf report: writing and finalizing the capture on shutdown "
              "(this can take a while for a large perf.data) ...")
        sigint_wait(perf_proc, 30)
        perf_proc = None

        for sp in perf_stat_procs:
            sigint_wait(sp, 15)
        perf_stat_procs = []

        # Validate the capture before rendering: an empty or header-only
        # perf.data renders to a useless flamegraph ("No stack counts found").
        # Read the sample count perf logged and fail loudly with the likely
        # cause instead.
        perf_log_text = ((out_dir / "perf.log").read_text(errors="replace")
                         if (out_dir / "perf.log").exists() else "")
        m = re.search(r"\((\d+)\s+samples\)", perf_log_text)
        n_samples = int(m.group(1)) if m else None
        empty = (not perf_data.exists() or perf_data.stat().st_size == 0
                 or n_samples == 0
                 or (n_samples is None and perf_data.stat().st_size < 100_000))
        if empty:
            print("ERROR: perf captured no usable samples - refusing to render "
                  "an empty flamegraph.", file=sys.stderr)
            print("  Likely causes: the sampling event did not open on this CPU "
                  "(hybrid P/E-core - the self-test should have caught this), the "
                  "profiled process was idle, or the kit exited mid-capture.",
                  file=sys.stderr)
            if perf_log_text.strip():
                sys.stderr.write("  perf.log:\n" + perf_log_text)
            return 1
        print(f"capture: {n_samples if n_samples is not None else 'unknown'} "
              "samples recorded.")

        if runner_rc != 0:
            print(f"{runner} test failed (rc={runner_rc}); see {out_dir}/browser.log",
                  file=sys.stderr)

        print("rendering flamegraph ...")
        # perf script | stackcollapse-perf.pl | sed | flamegraph.pl
        p1 = subprocess.Popen(
            [*sudo_perf, "perf", "script", "--no-inline",
             "-i", str(perf_data)],
            stdout=subprocess.PIPE,
        )
        p2 = subprocess.Popen(["stackcollapse-perf.pl"],
                              stdin=p1.stdout, stdout=subprocess.PIPE)
        p1.stdout.close()
        p3 = subprocess.Popen(["sed", "-E", "-s",
                               "s/^kitbgsv[^;]+/kitbgsv/"],
                              stdin=p2.stdout, stdout=subprocess.PIPE)
        p2.stdout.close()
        with (out_dir / "flamegraph.svg").open("wb") as svg:
            p4 = subprocess.Popen(["flamegraph.pl"],
                                  stdin=p3.stdout, stdout=svg)
            p3.stdout.close()
            p4.wait()
        for p in (p1, p2, p3):
            p.wait()

        # Post-render sanity check: how much of the capture actually resolved,
        # and to which process. A flamegraph dominated by [unknown] is the
        # jailed-kit case under system-wide/cgroup capture and is not useful.
        try:
            dso = subprocess.run(
                [*sudo_perf, "perf", "report", "--stdio", "--sort", "dso",
                 "-i", str(perf_data)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                timeout=180).stdout
            mu = re.search(r"^\s*([\d.]+)%.*\[unknown\]", dso, re.MULTILINE)
            unknown_pct = float(mu.group(1)) if mu else 0.0
            comm = subprocess.run(
                [*sudo_perf, "perf", "report", "--stdio", "--sort", "comm",
                 "-i", str(perf_data)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                timeout=180).stdout
            mk = re.search(r"^\s*([\d.]+)%.*kitbroker", comm, re.MULTILINE)
            kit_pct = float(mk.group(1)) if mk else 0.0
            print(f"flamegraph: {out_dir}/flamegraph.svg  "
                  f"(kit {kit_pct:.0f}%, unresolved {unknown_pct:.0f}%)")
            if unknown_pct >= 50.0:
                print(f"WARNING: {unknown_pct:.0f}% of samples are [unknown] - "
                      "symbols did not resolve. This is the jailed-kit case under "
                      "system-wide/cgroup capture; use pid mode (drop --cgroup) "
                      "and profile a single document for a symbolised flamegraph.",
                      file=sys.stderr)
        except Exception:
            pass

        total_elapsed = int(time.monotonic() - start_ts)
        print()
        print("done.")
        print(f"  {runner} elapsed : {runner_elapsed}s")
        print(f"  total elapsed: {total_elapsed}s")
        print(f"  {runner} log    : {out_dir}/browser.log")
        print(f"  perf data    : {perf_data}")
        print(f"  flamegraph   : {out_dir}/flamegraph.svg")

        # Gather and print the run summary, then write metrics.json.
        workload = collect_workload(out_dir / "browser.log")
        print_workload(workload)
        perf_by_label = collect_perf(out_dir)
        print_perf(perf_by_label)
        mem_by_label = mem_sampler.summary()
        print_memory(mem_by_label)

        # Machine-readable dump for plotting IPC / CPU time / memory across runs.
        metrics = {
            "out_dir": str(out_dir),
            "runner": runner,
            "test_script": test_script,
            "perf_event": perf_event,
            "runner_elapsed_s": runner_elapsed,
            "total_elapsed_s": total_elapsed,
            "flamegraph_samples": flamegraph_sample_count(out_dir),
            "workload": workload,
            "perf": perf_by_label,
            "memory": mem_by_label,
        }
        metrics_path = out_dir / "metrics.json"
        metrics_path.write_text(json.dumps(metrics, indent=2) + "\n")
        print(f"  metrics json : {metrics_path}")
        return runner_rc
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
