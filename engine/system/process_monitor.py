"""
CosySim Process Monitor — tracks system processes, git operations,
LMStudio instances, and Python workers with PID cross-referencing,
CPU/memory metrics, stall detection, and historical snapshots.

Usage::

    from engine.system.process_monitor import get_process_monitor

    mon = get_process_monitor()

    # Full system snapshot with categorized processes
    snap = mon.system_snapshot()

    # Git operations with phase detection
    git_ops = mon.git_operations()

    # Track a named operation (e.g., "push 388 commits")
    mon.track_operation("git-push-master", pid=53472, metadata={"commits": 388})

    # Process tree for any PID
    tree = mon.process_tree(53472)

    # Top CPU/memory consumers
    top = mon.top_consumers(10)

    # Stall detection
    stalls = mon.stall_detection()

CLI::

    python -m engine.system                    # One-shot snapshot
    python -m engine.system --watch            # Continuous monitoring (2s)
    python -m engine.system --git              # Git operations only
    python -m engine.system --pid 1234         # Process tree for PID
    python -m engine.system --top 10           # Top consumers
    python -m engine.system --track name pid   # Track a named operation
"""
from __future__ import annotations

import dataclasses
import enum
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_instance: Optional["ProcessMonitor"] = None


# ──── Data Models ────────────────────────────────────────────────────────


class ProcessCategory(str, enum.Enum):
    """Process classification categories."""
    GIT = "git"
    PYTHON = "python"
    LMSTUDIO = "lmstudio"
    NODE = "node"
    CHROME = "chrome"
    COMFYUI = "comfyui"
    SYSTEM = "system"
    OTHER = "other"


class GitPhase(str, enum.Enum):
    """Git operation phases."""
    CREDENTIAL = "credential"
    NEGOTIATION = "negotiation"
    PACKING = "packing"
    UPLOADING = "uploading"
    RECEIVING = "receiving"
    RESOLVING = "resolving"
    INDEXING = "indexing"
    IDLE = "idle"
    UNKNOWN = "unknown"


class GitOpType(str, enum.Enum):
    """Git operation types."""
    PUSH = "push"
    PULL = "pull"
    FETCH = "fetch"
    CLONE = "clone"
    GC = "gc"
    REPACK = "repack"
    UNKNOWN = "unknown"


@dataclasses.dataclass
class ProcessInfo:
    """Snapshot of a single process."""
    pid: int
    name: str
    cmdline: List[str]
    cpu_seconds: float
    cpu_percent: float
    memory_mb: float
    memory_percent: float
    status: str
    parent_pid: Optional[int]
    children_pids: List[int]
    create_time: float
    username: Optional[str]
    category: ProcessCategory
    io_read_bytes: Optional[int] = None
    io_write_bytes: Optional[int] = None
    num_threads: int = 0
    open_files_count: int = 0

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.create_time

    @property
    def uptime_human(self) -> str:
        secs = self.uptime_seconds
        if secs < 60:
            return f"{secs:.0f}s"
        if secs < 3600:
            return f"{secs / 60:.1f}m"
        return f"{secs / 3600:.1f}h"

    @property
    def cmdline_str(self) -> str:
        return " ".join(self.cmdline) if self.cmdline else self.name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pid": self.pid,
            "name": self.name,
            "cmdline": self.cmdline_str,
            "cpu_seconds": round(self.cpu_seconds, 2),
            "cpu_percent": round(self.cpu_percent, 1),
            "memory_mb": round(self.memory_mb, 1),
            "memory_percent": round(self.memory_percent, 1),
            "status": self.status,
            "parent_pid": self.parent_pid,
            "children": self.children_pids,
            "uptime": self.uptime_human,
            "category": self.category.value,
            "num_threads": self.num_threads,
            "io_read_mb": round(self.io_read_bytes / (1024 * 1024), 1) if self.io_read_bytes else None,
            "io_write_mb": round(self.io_write_bytes / (1024 * 1024), 1) if self.io_write_bytes else None,
        }


@dataclasses.dataclass
class GitOperation:
    """Tracked git operation with phase detection and progress estimation."""
    op_type: GitOpType
    phase: GitPhase
    pids: List[int]
    start_time: float
    remote_url: Optional[str] = None
    branch: Optional[str] = None
    pack_pid: Optional[int] = None
    pack_memory_mb: float = 0.0
    pack_cpu_seconds: float = 0.0
    transfer_pid: Optional[int] = None
    commit_count: Optional[int] = None
    estimated_progress: Optional[float] = None
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def elapsed_human(self) -> str:
        secs = self.elapsed_seconds
        if secs < 60:
            return f"{secs:.0f}s"
        if secs < 3600:
            return f"{secs / 60:.1f}m"
        return f"{secs / 3600:.1f}h"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.op_type.value,
            "phase": self.phase.value,
            "pids": self.pids,
            "elapsed": self.elapsed_human,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "remote": self.remote_url,
            "branch": self.branch,
            "pack": {
                "pid": self.pack_pid,
                "memory_mb": round(self.pack_memory_mb, 1),
                "cpu_seconds": round(self.pack_cpu_seconds, 1),
            } if self.pack_pid else None,
            "commit_count": self.commit_count,
            "estimated_progress": self.estimated_progress,
            "metadata": self.metadata,
        }


@dataclasses.dataclass
class TrackedOperation:
    """A user-registered named operation with PID cross-referencing."""
    id: str
    name: str
    category: str
    pids: List[int]
    start_time: float
    status: str = "running"
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)
    _cpu_checkpoints: List[Tuple[float, float]] = dataclasses.field(
        default_factory=list, repr=False
    )

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def elapsed_human(self) -> str:
        secs = self.elapsed_seconds
        if secs < 60:
            return f"{secs:.0f}s"
        if secs < 3600:
            return f"{secs / 60:.1f}m"
        return f"{secs / 3600:.1f}h"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "pids": self.pids,
            "elapsed": self.elapsed_human,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "status": self.status,
            "metadata": self.metadata,
        }


@dataclasses.dataclass
class StallInfo:
    """Report of a potentially stalled process."""
    pid: int
    name: str
    cpu_seconds_delta: float
    check_interval: float
    memory_mb: float
    uptime_seconds: float
    verdict: str  # "stalled", "slow", "active"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pid": self.pid,
            "name": self.name,
            "cpu_delta": round(self.cpu_seconds_delta, 3),
            "check_interval_s": round(self.check_interval, 1),
            "memory_mb": round(self.memory_mb, 1),
            "uptime_s": round(self.uptime_seconds, 1),
            "verdict": self.verdict,
        }


# ──── Process Classification ────────────────────────────────────────────


_CATEGORY_PATTERNS: Dict[ProcessCategory, List[str]] = {
    ProcessCategory.GIT: [
        "git", "git.exe", "git-remote-https", "git-remote-https.exe",
        "git-upload-pack", "git-receive-pack",
    ],
    ProcessCategory.PYTHON: ["python", "python.exe", "python3", "python3.exe", "pythonw.exe"],
    ProcessCategory.LMSTUDIO: ["lms", "lms.exe", "lmstudio", "lmstudio.exe", "lm-studio", "lm studio"],
    ProcessCategory.NODE: ["node", "node.exe", "npm", "npm.exe", "npx", "npx.exe"],
    ProcessCategory.CHROME: [
        "chrome", "chrome.exe", "chromium", "chromium.exe",
        "msedge", "msedge.exe",
    ],
    ProcessCategory.COMFYUI: [],  # detected by cmdline
}

_GIT_OP_CMDLINE_PATTERNS: Dict[GitOpType, List[str]] = {
    GitOpType.PUSH: ["push", "send-pack"],
    GitOpType.PULL: ["pull", "fetch-pack"],
    GitOpType.FETCH: ["fetch"],
    GitOpType.CLONE: ["clone"],
    GitOpType.GC: ["gc", "prune"],
    GitOpType.REPACK: ["repack", "pack-objects"],
}

_GIT_PHASE_PATTERNS: Dict[GitPhase, List[str]] = {
    GitPhase.CREDENTIAL: ["credential", "auth"],
    GitPhase.PACKING: ["pack-objects"],
    GitPhase.UPLOADING: ["send-pack", "remote-https"],
    GitPhase.RECEIVING: ["receive-pack", "fetch-pack", "index-pack"],
    GitPhase.RESOLVING: ["resolve-undo", "update-ref"],
    GitPhase.INDEXING: ["index-pack"],
}


def _classify_process_name(name: str) -> ProcessCategory:
    """Classify a process by its executable name."""
    name_lower = name.lower().strip()
    for category, patterns in _CATEGORY_PATTERNS.items():
        if name_lower in patterns:
            return category
    return ProcessCategory.OTHER


def _classify_by_cmdline(cmdline: List[str], name: str) -> ProcessCategory:
    """Classify a process by its command line, with fallback to name."""
    cmdline_str = " ".join(cmdline).lower()

    if "comfyui" in cmdline_str or "comfy" in cmdline_str:
        return ProcessCategory.COMFYUI

    if "lmstudio" in cmdline_str or "lm-studio" in cmdline_str or "lm studio" in cmdline_str:
        return ProcessCategory.LMSTUDIO

    return _classify_process_name(name)


def _detect_git_op_type(cmdline: List[str]) -> GitOpType:
    """Detect git operation type from command line arguments."""
    cmdline_str = " ".join(cmdline).lower()
    for op_type, patterns in _GIT_OP_CMDLINE_PATTERNS.items():
        for pattern in patterns:
            if pattern in cmdline_str:
                return op_type
    return GitOpType.UNKNOWN


def _detect_git_phase(process_name: str, cmdline: List[str]) -> GitPhase:
    """Detect git operation phase from process name and cmdline."""
    combined = (process_name + " " + " ".join(cmdline)).lower()
    for phase, patterns in _GIT_PHASE_PATTERNS.items():
        for pattern in patterns:
            if pattern in combined:
                return phase
    return GitPhase.UNKNOWN


def _extract_git_remote(cmdline: List[str]) -> Optional[str]:
    """Extract remote URL from git command line."""
    for i, arg in enumerate(cmdline):
        if arg.startswith("https://") or arg.startswith("git@") or arg.startswith("ssh://"):
            return arg
        if arg.endswith(".git") and i > 0:
            return arg
    return None


def _extract_git_branch(cmdline: List[str]) -> Optional[str]:
    """Extract branch name from git command line."""
    for arg in cmdline:
        if arg in ("master", "main", "develop", "dev"):
            return arg
    for i, arg in enumerate(cmdline):
        if arg in ("--branch", "-b") and i + 1 < len(cmdline):
            return cmdline[i + 1]
    return None


# ──── Process Monitor Core ──────────────────────────────────────────────


class ProcessMonitor:
    """System process monitor with git operation awareness and cross-referencing.

    Singleton. Use ``get_process_monitor()`` to obtain the instance.
    """

    def __init__(self) -> None:
        self._tracked: Dict[str, TrackedOperation] = {}
        self._cpu_baselines: Dict[int, Tuple[float, float]] = {}  # pid → (timestamp, cpu_seconds)
        self._snapshot_history: List[Dict[str, Any]] = []
        self._max_history = 100
        self._lock = threading.Lock()

    # ── Process Scanning ─────────────────────────────────────────────

    def _get_process_info(self, proc: Any) -> Optional[ProcessInfo]:
        """Build a ProcessInfo from a psutil.Process, returning None on failure."""
        try:
            import psutil
            with proc.oneshot():
                try:
                    name = proc.name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    return None

                try:
                    cmdline = proc.cmdline()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    cmdline = []

                try:
                    cpu_times = proc.cpu_times()
                    cpu_seconds = cpu_times.user + cpu_times.system
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    cpu_seconds = 0.0

                try:
                    cpu_percent = proc.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    cpu_percent = 0.0

                try:
                    mem_info = proc.memory_info()
                    memory_mb = mem_info.rss / (1024 * 1024)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    memory_mb = 0.0

                try:
                    memory_percent = proc.memory_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    memory_percent = 0.0

                try:
                    status = proc.status()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    status = "unknown"

                try:
                    parent_pid = proc.ppid()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    parent_pid = None

                try:
                    children_pids = [c.pid for c in proc.children()]
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    children_pids = []

                try:
                    create_time = proc.create_time()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    create_time = time.time()

                try:
                    username = proc.username()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    username = None

                io_read = None
                io_write = None
                try:
                    io_counters = proc.io_counters()
                    io_read = io_counters.read_bytes
                    io_write = io_counters.write_bytes
                except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                    pass

                try:
                    num_threads = proc.num_threads()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    num_threads = 0

                category = _classify_by_cmdline(cmdline, name)

                return ProcessInfo(
                    pid=proc.pid,
                    name=name,
                    cmdline=cmdline,
                    cpu_seconds=cpu_seconds,
                    cpu_percent=cpu_percent,
                    memory_mb=memory_mb,
                    memory_percent=memory_percent,
                    status=status,
                    parent_pid=parent_pid,
                    children_pids=children_pids,
                    create_time=create_time,
                    username=username,
                    category=category,
                    io_read_bytes=io_read,
                    io_write_bytes=io_write,
                    num_threads=num_threads,
                )
        except Exception:
            return None

    def scan_all(self) -> Dict[str, List[ProcessInfo]]:
        """Scan all processes and return them categorized.

        Returns:
            Dict mapping category names to lists of ProcessInfo.
        """
        try:
            import psutil
        except ImportError:
            logger.error("psutil not installed — cannot scan processes")
            return {}

        categorized: Dict[str, List[ProcessInfo]] = {cat.value: [] for cat in ProcessCategory}

        for proc in psutil.process_iter():
            info = self._get_process_info(proc)
            if info is not None:
                categorized[info.category.value].append(info)

        return categorized

    def scan_category(self, category: ProcessCategory) -> List[ProcessInfo]:
        """Scan and return processes of a specific category."""
        try:
            import psutil
        except ImportError:
            return []

        results: List[ProcessInfo] = []
        for proc in psutil.process_iter():
            info = self._get_process_info(proc)
            if info is not None and info.category == category:
                results.append(info)
        return results

    # ── Git Operation Tracking ───────────────────────────────────────

    def git_operations(self) -> List[GitOperation]:
        """Detect and analyze all active git operations.

        Walks the process tree to find git parent processes, then
        identifies child processes (pack-objects, remote-https, etc.)
        to determine the operation type and current phase.

        Returns:
            List of GitOperation objects describing active operations.
        """
        git_procs = self.scan_category(ProcessCategory.GIT)
        if not git_procs:
            return []

        # Build PID → ProcessInfo map
        pid_map: Dict[int, ProcessInfo] = {p.pid: p for p in git_procs}

        # Find root git processes (those whose parent is NOT a git process)
        root_pids: Set[int] = set()
        for p in git_procs:
            if p.parent_pid not in pid_map:
                root_pids.add(p.pid)

        # For each root, build a GitOperation
        operations: List[GitOperation] = []
        for root_pid in root_pids:
            root_info = pid_map[root_pid]

            # Collect all descendant PIDs
            tree_pids = self._collect_descendants(root_pid, pid_map)
            all_pids = [root_pid] + tree_pids

            # Determine operation type from root cmdline
            op_type = _detect_git_op_type(root_info.cmdline)

            # Determine current phase from the deepest active process
            phase = GitPhase.UNKNOWN
            pack_pid: Optional[int] = None
            pack_mem = 0.0
            pack_cpu = 0.0
            transfer_pid: Optional[int] = None

            for pid in all_pids:
                info = pid_map.get(pid)
                if not info:
                    continue
                detected = _detect_git_phase(info.name, info.cmdline)
                if detected == GitPhase.PACKING:
                    phase = GitPhase.PACKING
                    pack_pid = pid
                    pack_mem = info.memory_mb
                    pack_cpu = info.cpu_seconds
                elif detected == GitPhase.UPLOADING:
                    if phase != GitPhase.PACKING:
                        phase = GitPhase.UPLOADING
                    transfer_pid = pid
                elif detected == GitPhase.CREDENTIAL:
                    if phase == GitPhase.UNKNOWN:
                        phase = GitPhase.CREDENTIAL
                elif detected != GitPhase.UNKNOWN:
                    if phase == GitPhase.UNKNOWN:
                        phase = detected

            remote_url = _extract_git_remote(root_info.cmdline)
            branch = _extract_git_branch(root_info.cmdline)

            op = GitOperation(
                op_type=op_type,
                phase=phase,
                pids=all_pids,
                start_time=root_info.create_time,
                remote_url=remote_url,
                branch=branch,
                pack_pid=pack_pid,
                pack_memory_mb=pack_mem,
                pack_cpu_seconds=pack_cpu,
                transfer_pid=transfer_pid,
            )

            # Enrich with tracked operation metadata
            for tracked in self._tracked.values():
                if set(tracked.pids) & set(all_pids):
                    op.commit_count = tracked.metadata.get("commits")
                    op.metadata.update(tracked.metadata)
                    break

            operations.append(op)

        return operations

    def _collect_descendants(
        self, pid: int, pid_map: Dict[int, ProcessInfo]
    ) -> List[int]:
        """Recursively collect all descendant PIDs."""
        descendants: List[int] = []
        info = pid_map.get(pid)
        if not info:
            return descendants
        for child_pid in info.children_pids:
            descendants.append(child_pid)
            descendants.extend(self._collect_descendants(child_pid, pid_map))
        return descendants

    # ── Named Operation Tracking ─────────────────────────────────────

    def track_operation(
        self,
        name: str,
        pid: int,
        category: str = "user",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TrackedOperation:
        """Register a named operation for cross-referencing with process data.

        Args:
            name: Human-readable operation name (e.g., "git-push-master").
            pid: Root PID of the operation.
            category: Classification (e.g., "git", "build", "test").
            metadata: Extra context (e.g., {"commits": 388}).

        Returns:
            The TrackedOperation object.
        """
        op = TrackedOperation(
            id=f"{name}-{pid}",
            name=name,
            category=category,
            pids=[pid],
            start_time=time.time(),
            metadata=metadata or {},
        )
        with self._lock:
            self._tracked[name] = op
        logger.info("Tracking operation %r (PID %d, category=%s)", name, pid, category)
        return op

    def untrack_operation(self, name: str) -> Optional[TrackedOperation]:
        """Unregister a tracked operation by name."""
        with self._lock:
            op = self._tracked.pop(name, None)
        if op:
            op.status = "completed"
            logger.info("Untracked operation %r after %.1fs", name, op.elapsed_seconds)
        return op

    def tracked_operations(self) -> List[TrackedOperation]:
        """Return all currently tracked operations."""
        with self._lock:
            return list(self._tracked.values())

    def update_tracked_pids(self, name: str) -> Optional[TrackedOperation]:
        """Refresh the PID list for a tracked operation (re-scans process tree)."""
        with self._lock:
            op = self._tracked.get(name)
        if not op or not op.pids:
            return op

        try:
            import psutil
            root_pid = op.pids[0]
            try:
                root = psutil.Process(root_pid)
                children = root.children(recursive=True)
                op.pids = [root_pid] + [c.pid for c in children]
            except psutil.NoSuchProcess:
                op.status = "exited"
        except ImportError:
            pass
        return op

    # ── Process Tree ─────────────────────────────────────────────────

    def process_tree(self, pid: int) -> Dict[str, Any]:
        """Build a process tree rooted at the given PID.

        Args:
            pid: Root PID to inspect.

        Returns:
            Nested dict with process info and children.
        """
        try:
            import psutil
        except ImportError:
            return {"error": "psutil not installed"}

        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return {"error": f"PID {pid} not found"}

        return self._build_tree_node(proc)

    def _build_tree_node(self, proc: Any) -> Dict[str, Any]:
        """Recursively build a tree node for a process."""
        info = self._get_process_info(proc)
        if not info:
            return {"pid": proc.pid, "error": "access denied"}

        node = info.to_dict()
        try:
            children = proc.children(recursive=False)
            if children:
                node["children_tree"] = [
                    self._build_tree_node(child) for child in children
                ]
        except Exception:
            pass

        # Cross-reference with tracked operations
        for tracked in self._tracked.values():
            if proc.pid in tracked.pids:
                node["tracked_operation"] = tracked.to_dict()
                break

        return node

    def process_info(self, pid: int) -> Optional[ProcessInfo]:
        """Get ProcessInfo for a single PID."""
        try:
            import psutil
            proc = psutil.Process(pid)
            return self._get_process_info(proc)
        except Exception:
            return None

    # ── Top Consumers ────────────────────────────────────────────────

    def top_consumers(
        self,
        n: int = 10,
        sort_by: str = "cpu_seconds",
    ) -> List[ProcessInfo]:
        """Return the top N processes by CPU time or memory usage.

        Args:
            n: Number of top processes to return.
            sort_by: "cpu_seconds", "cpu_percent", "memory_mb", or "memory_percent".

        Returns:
            List of ProcessInfo sorted descending by the chosen metric.
        """
        try:
            import psutil
        except ImportError:
            return []

        all_procs: List[ProcessInfo] = []
        for proc in psutil.process_iter():
            info = self._get_process_info(proc)
            if info is not None and info.pid != os.getpid():
                all_procs.append(info)

        key_map = {
            "cpu_seconds": lambda p: p.cpu_seconds,
            "cpu_percent": lambda p: p.cpu_percent,
            "memory_mb": lambda p: p.memory_mb,
            "memory_percent": lambda p: p.memory_percent,
        }
        key_fn = key_map.get(sort_by, key_map["cpu_seconds"])
        all_procs.sort(key=key_fn, reverse=True)
        return all_procs[:n]

    # ── Stall Detection ──────────────────────────────────────────────

    def stall_detection(
        self,
        pids: Optional[List[int]] = None,
        check_interval: float = 3.0,
    ) -> List[StallInfo]:
        """Check if specified processes (or tracked ops) are stalled.

        Compares CPU time at two points separated by ``check_interval`` seconds.
        A process with zero CPU delta is flagged as stalled.

        Args:
            pids: PIDs to check. If None, checks all tracked operations.
            check_interval: Seconds between the two measurements.

        Returns:
            List of StallInfo objects with verdicts.
        """
        try:
            import psutil
        except ImportError:
            return []

        if pids is None:
            pids = []
            for op in self._tracked.values():
                pids.extend(op.pids)

        if not pids:
            return []

        # Take first measurement
        before: Dict[int, Tuple[float, float]] = {}
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                ct = proc.cpu_times()
                before[pid] = (ct.user + ct.system, proc.memory_info().rss / (1024 * 1024))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        time.sleep(check_interval)

        # Take second measurement and compare
        results: List[StallInfo] = []
        for pid, (cpu_before, mem_before) in before.items():
            try:
                proc = psutil.Process(pid)
                ct = proc.cpu_times()
                cpu_after = ct.user + ct.system
                mem_now = proc.memory_info().rss / (1024 * 1024)
                delta = cpu_after - cpu_before
                uptime = time.time() - proc.create_time()

                if delta < 0.001:
                    verdict = "stalled"
                elif delta < 0.1:
                    verdict = "slow"
                else:
                    verdict = "active"

                results.append(StallInfo(
                    pid=pid,
                    name=proc.name(),
                    cpu_seconds_delta=delta,
                    check_interval=check_interval,
                    memory_mb=mem_now,
                    uptime_seconds=uptime,
                    verdict=verdict,
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                results.append(StallInfo(
                    pid=pid,
                    name="<exited>",
                    cpu_seconds_delta=0.0,
                    check_interval=check_interval,
                    memory_mb=0.0,
                    uptime_seconds=0.0,
                    verdict="exited",
                ))

        return results

    # ── Full System Snapshot ─────────────────────────────────────────

    def system_snapshot(self) -> Dict[str, Any]:
        """Full system snapshot with resources, categorized processes,
        git operations, and tracked operations.

        Returns:
            Comprehensive dict suitable for dashboards or logging.
        """
        snapshot: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
        }

        # System resources from existing SystemMonitor
        try:
            from engine.logging.monitor import get_system_monitor
            sys_mon = get_system_monitor()
            snapshot["system"] = sys_mon.snapshot()
        except Exception as exc:
            snapshot["system"] = {"error": str(exc)}

        # Categorized process counts and key processes
        categorized = self.scan_all()
        process_summary: Dict[str, Any] = {}
        for cat, procs in categorized.items():
            if procs:
                process_summary[cat] = {
                    "count": len(procs),
                    "total_cpu_seconds": round(sum(p.cpu_seconds for p in procs), 1),
                    "total_memory_mb": round(sum(p.memory_mb for p in procs), 1),
                    "processes": [p.to_dict() for p in sorted(
                        procs, key=lambda x: x.cpu_seconds, reverse=True
                    )[:5]],  # top 5 per category
                }
        snapshot["processes"] = process_summary

        # Git operations
        git_ops = self.git_operations()
        snapshot["git_operations"] = [op.to_dict() for op in git_ops]

        # Tracked operations
        tracked = self.tracked_operations()
        snapshot["tracked_operations"] = [op.to_dict() for op in tracked]

        # Top consumers
        top = self.top_consumers(5, "cpu_seconds")
        snapshot["top_cpu"] = [p.to_dict() for p in top]

        top_mem = self.top_consumers(5, "memory_mb")
        snapshot["top_memory"] = [p.to_dict() for p in top_mem]

        # Store in history
        with self._lock:
            self._snapshot_history.append(snapshot)
            if len(self._snapshot_history) > self._max_history:
                self._snapshot_history = self._snapshot_history[-self._max_history:]

        return snapshot

    def snapshot_history(self) -> List[Dict[str, Any]]:
        """Return stored snapshot history."""
        with self._lock:
            return list(self._snapshot_history)

    # ── Continuous Watch ─────────────────────────────────────────────

    def watch(
        self,
        interval: float = 2.0,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        max_iterations: int = 0,
        git_only: bool = False,
    ) -> None:
        """Continuously monitor and optionally invoke callback with snapshots.

        Args:
            interval: Seconds between snapshots.
            callback: Called with each snapshot dict. If None, prints to stdout.
            max_iterations: Stop after this many iterations (0 = infinite).
            git_only: Only track git operations (lighter weight).
        """
        iteration = 0
        try:
            while max_iterations == 0 or iteration < max_iterations:
                iteration += 1
                if git_only:
                    ops = self.git_operations()
                    data = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "git_operations": [op.to_dict() for op in ops],
                        "iteration": iteration,
                    }
                else:
                    data = self.system_snapshot()
                    data["iteration"] = iteration

                if callback:
                    callback(data)
                else:
                    _print_snapshot(data, git_only=git_only)

                time.sleep(interval)
        except KeyboardInterrupt:
            pass

    # ── Metrics DB Integration ───────────────────────────────────────

    def record_to_metrics_db(self) -> bool:
        """Record current snapshot to the observability metrics DB.

        Records both the full process snapshot to ``process_snapshots``
        and individual git operations as pipeline metrics.

        Returns:
            True if successfully recorded, False otherwise.
        """
        try:
            from engine.observability.metrics_db import get_metrics_db
            db = get_metrics_db()
            snapshot = self.system_snapshot()

            proc_count = snapshot.get("total_processes", 0)
            git_ops = snapshot.get("git_operations", [])
            tracked = snapshot.get("tracked_operations", [])
            stalled = snapshot.get("stalled", [])
            cpu_s = snapshot.get("total_cpu_seconds", 0.0)
            mem_mb = snapshot.get("total_memory_mb", 0.0)

            db.record_process_snapshot(
                category="all",
                process_count=proc_count,
                total_cpu_seconds=cpu_s,
                total_memory_mb=mem_mb,
                git_op_count=len(git_ops),
                tracked_op_count=len(tracked),
                stalled_count=len(stalled),
                snapshot_json=json.dumps(snapshot, default=str),
            )
            return True
        except Exception as exc:
            logger.debug("Failed to record to metrics DB: %s", exc)
            return False

    # ── LMStudio Process Info ────────────────────────────────────────

    def lmstudio_processes(self) -> List[ProcessInfo]:
        """Return all LMStudio-related processes."""
        return self.scan_category(ProcessCategory.LMSTUDIO)

    def python_workers(self) -> List[ProcessInfo]:
        """Return all Python processes (excluding current process)."""
        procs = self.scan_category(ProcessCategory.PYTHON)
        return [p for p in procs if p.pid != os.getpid()]


# ──── Singleton ──────────────────────────────────────────────────────────


def get_process_monitor() -> ProcessMonitor:
    """Return the singleton ProcessMonitor instance."""
    global _instance
    if _instance is not None:
        return _instance
    with _lock:
        if _instance is not None:
            return _instance
        _instance = ProcessMonitor()
        return _instance


# ──── CLI Output Formatting ──────────────────────────────────────────────


def _format_table(
    headers: List[str],
    rows: List[List[str]],
    col_widths: Optional[List[int]] = None,
) -> str:
    """Format a simple ASCII table."""
    if not rows:
        return "(no data)"

    if col_widths is None:
        col_widths = [
            max(len(str(h)), max((len(str(row[i])) for row in rows), default=0))
            for i, h in enumerate(headers)
        ]

    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    separator = "  ".join("-" * w for w in col_widths)
    data_lines = []
    for row in rows:
        data_lines.append("  ".join(
            str(cell).ljust(w) for cell, w in zip(row, col_widths)
        ))

    return "\n".join([header_line, separator] + data_lines)


def _print_snapshot(data: Dict[str, Any], git_only: bool = False) -> None:
    """Print a snapshot to stdout in a human-readable format."""
    ts = data.get("timestamp", "?")
    print(f"\n{'═' * 72}")
    print(f"  System Monitor — {ts}")
    print(f"{'═' * 72}")

    if not git_only:
        # System resources
        sys_data = data.get("system", {})
        cpu = sys_data.get("cpu_percent", "?")
        ram_pct = sys_data.get("ram_percent", "?")
        ram_used = sys_data.get("ram_used_gb", "?")
        ram_total = sys_data.get("ram_total_gb", "?")
        gpu = sys_data.get("gpu", {})
        vram_used = gpu.get("vram_used_mb", "?")
        vram_total = gpu.get("vram_total_mb", "?")
        gpu_name = gpu.get("name", "N/A")
        gpu_temp = gpu.get("temp_c", "?")

        print(f"\n  CPU: {cpu}%  |  RAM: {ram_used}/{ram_total} GB ({ram_pct}%)")
        if gpu.get("available"):
            print(f"  GPU: {gpu_name}  |  VRAM: {vram_used}/{vram_total} MB  |  Temp: {gpu_temp}°C")

        # Process summary
        procs = data.get("processes", {})
        if procs:
            print(f"\n  Process Categories:")
            for cat, info in procs.items():
                cnt = info.get("count", 0)
                cpu_s = info.get("total_cpu_seconds", 0)
                mem_mb = info.get("total_memory_mb", 0)
                print(f"    {cat:12s}  {cnt:3d} procs  {cpu_s:8.1f} CPU-s  {mem_mb:8.1f} MB")

        # Top CPU
        top_cpu = data.get("top_cpu", [])
        if top_cpu:
            print(f"\n  Top CPU Consumers:")
            headers = ["PID", "Name", "CPU-s", "CPU%", "Mem MB", "Uptime", "Command"]
            rows = []
            for p in top_cpu:
                cmd = p.get("cmdline", "")
                if len(cmd) > 40:
                    cmd = cmd[:37] + "..."
                rows.append([
                    str(p["pid"]), p["name"],
                    f"{p['cpu_seconds']:.1f}", f"{p['cpu_percent']:.1f}",
                    f"{p['memory_mb']:.1f}", p["uptime"], cmd,
                ])
            print("    " + _format_table(headers, rows).replace("\n", "\n    "))

    # Git operations
    git_ops = data.get("git_operations", [])
    if git_ops:
        print(f"\n  Git Operations ({len(git_ops)}):")
        for op in git_ops:
            op_type = op.get("type", "?")
            phase = op.get("phase", "?")
            elapsed = op.get("elapsed", "?")
            pids = op.get("pids", [])
            remote = op.get("remote") or "?"
            branch = op.get("branch") or "?"
            pack = op.get("pack")

            print(f"    [{op_type.upper()}] phase={phase}  elapsed={elapsed}  branch={branch}")
            print(f"      remote: {remote}")
            print(f"      PIDs: {pids}")
            if pack and pack.get("pid"):
                print(f"      pack-objects: PID {pack['pid']}  "
                      f"CPU={pack['cpu_seconds']:.1f}s  Mem={pack['memory_mb']:.1f} MB")
            if op.get("commit_count"):
                print(f"      commits: {op['commit_count']}")
    else:
        if git_only:
            print("\n  No active git operations.")

    # Tracked operations
    tracked = data.get("tracked_operations", [])
    if tracked:
        print(f"\n  Tracked Operations ({len(tracked)}):")
        for t in tracked:
            print(f"    [{t['status'].upper()}] {t['name']}  "
                  f"elapsed={t['elapsed']}  PIDs={t['pids']}")
            if t.get("metadata"):
                for k, v in t["metadata"].items():
                    print(f"      {k}: {v}")

    print()
