"""Deterministic, dependency-free environment probes for the portability spike.

The module reports observations only.  Availability of an executable or an
installed target is not treated as proof that a platform can be built or run.
All subprocesses use argv lists, have a deadline, and keep only a bounded output
preview while hashing the complete captured byte streams.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import signal
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Iterable, Mapping, Sequence


DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024
DEFAULT_MAX_INPUT_BYTES = 1024 * 1024
DEFAULT_EXECUTABLES = (
    "cargo",
    "cargo-ndk",
    "docker",
    "dotnet",
    "go",
    "node",
    "podman",
    "python",
    "python3",
    "rustc",
    "rustup",
    "wsl",
)


def _is_filesystem_root(value: str) -> bool:
    path = Path(value)
    try:
        return path == Path(path.anchor)
    except OSError:
        return False


def _private_roots(
    extra_roots: Iterable[tuple[str | os.PathLike[str], str]] = (),
) -> list[tuple[str, str]]:
    """Return host-specific path prefixes ordered from most to least specific."""

    candidates: list[tuple[str, str]] = []
    environment_roots = (
        ("ANDROID_SDK_ROOT", "<ANDROID_SDK>"),
        ("ANDROID_HOME", "<ANDROID_SDK>"),
        ("ANDROID_NDK_HOME", "<ANDROID_NDK>"),
        ("ANDROID_NDK_ROOT", "<ANDROID_NDK>"),
    )
    for variable, placeholder in environment_roots:
        value = os.environ.get(variable)
        if value:
            candidates.append((value, placeholder))

    candidates.extend(
        (
            (tempfile.gettempdir(), "<TEMP>"),
            (str(Path.cwd()), "<CWD>"),
            (str(Path.home()), "<HOME>"),
        )
    )
    candidates.extend((os.fspath(path), placeholder) for path, placeholder in extra_roots)

    unique: dict[str, tuple[str, str]] = {}
    for raw_path, placeholder in candidates:
        if not raw_path:
            continue
        expanded = os.path.abspath(os.path.expanduser(raw_path))
        if _is_filesystem_root(expanded):
            continue
        key = os.path.normcase(os.path.normpath(expanded))
        unique[key] = (expanded.rstrip("\\/"), placeholder)

    return sorted(unique.values(), key=lambda item: len(item[0]), reverse=True)


def _path_spellings(path: str) -> set[str]:
    spellings = {
        path,
        os.path.normpath(path),
        path.replace("\\", "/"),
        path.replace("/", "\\"),
    }
    return {value.rstrip("\\/") for value in spellings if value}


def sanitize_text(
    value: str,
    *,
    extra_roots: Iterable[tuple[str | os.PathLike[str], str]] = (),
) -> str:
    """Remove known user/workspace path prefixes and normalize line endings."""

    sanitized = value.replace("\r\n", "\n").replace("\r", "\n")
    flags = re.IGNORECASE if os.name == "nt" else 0
    for root, placeholder in _private_roots(extra_roots):
        for spelling in sorted(_path_spellings(root), key=len, reverse=True):
            pattern = re.escape(spelling) + r"(?=$|[\\/])"
            sanitized = re.sub(pattern, placeholder, sanitized, flags=flags)
    return sanitized


def sanitize_path(
    path: str | os.PathLike[str],
    *,
    extra_roots: Iterable[tuple[str | os.PathLike[str], str]] = (),
) -> str:
    """Return a stable display path without a user-specific absolute prefix."""

    absolute = os.path.abspath(os.path.expanduser(os.fspath(path)))
    return sanitize_text(absolute, extra_roots=extra_roots).replace("\\", "/")


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 digest for ``data``."""

    return hashlib.sha256(data).hexdigest()


def sha256_file(
    path: str | os.PathLike[str],
    *,
    chunk_size: int = 1024 * 1024,
) -> str:
    """Hash a file without loading it into memory."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_fingerprint(path: str | os.PathLike[str]) -> dict[str, object]:
    """Return a sanitized path, size, and SHA-256 for a regular file."""

    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError(f"not a regular file: {sanitize_path(file_path)}")
    return {
        "path": sanitize_path(file_path),
        "size_bytes": file_path.stat().st_size,
        "sha256": sha256_file(file_path),
    }


class _BoundedCapture:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.total_bytes = 0
        self.preview = bytearray()
        self.digest = hashlib.sha256()
        self.read_error: str | None = None

    def drain(self, stream: object) -> None:
        try:
            while True:
                chunk = stream.read(64 * 1024)  # type: ignore[attr-defined]
                if not chunk:
                    break
                self.total_bytes += len(chunk)
                self.digest.update(chunk)
                remaining = self.limit - len(self.preview)
                if remaining > 0:
                    self.preview.extend(chunk[:remaining])
        except (OSError, ValueError) as error:
            self.read_error = sanitize_text(str(error))
        finally:
            try:
                stream.close()  # type: ignore[attr-defined]
            except (OSError, ValueError):
                pass

    def observation(self) -> dict[str, object]:
        truncated = self.total_bytes > len(self.preview)
        decoded = bytes(self.preview).decode("utf-8", errors="replace")
        safe_text = sanitize_text(decoded)
        observation: dict[str, object] = {
            "size_bytes": self.total_bytes,
            "sha256": self.digest.hexdigest(),
            "truncated": truncated,
            "text": None if truncated else safe_text,
            "preview": safe_text if truncated else None,
        }
        if self.read_error is not None:
            observation["read_error"] = self.read_error
        return observation


class _BoundedInputWriter:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.write_error: str | None = None

    def write(self, stream: object) -> None:
        try:
            stream.write(self.payload)  # type: ignore[attr-defined]
            stream.flush()  # type: ignore[attr-defined]
        except (BrokenPipeError, OSError, ValueError) as error:
            self.write_error = sanitize_text(f"{type(error).__name__}: {error}")
        finally:
            try:
                stream.close()  # type: ignore[attr-defined]
            except (OSError, ValueError):
                pass

    def observation(self) -> dict[str, object]:
        observation: dict[str, object] = {
            "size_bytes": len(self.payload),
            "sha256": sha256_bytes(self.payload),
        }
        if self.write_error is not None:
            observation["write_error"] = self.write_error
        return observation


def _coerce_argv(argv: Sequence[str | os.PathLike[str]]) -> list[str]:
    if isinstance(argv, (str, bytes, os.PathLike)):
        raise TypeError("argv must be a sequence, never a shell command string")
    converted: list[str] = []
    for item in argv:
        if not isinstance(item, (str, os.PathLike)):
            raise TypeError("each argv item must be a string or path-like object")
        converted.append(os.fspath(item))
    if not converted:
        raise ValueError("argv must not be empty")
    return converted


def _empty_stream_observation() -> dict[str, object]:
    return {
        "size_bytes": 0,
        "sha256": sha256_bytes(b""),
        "truncated": False,
        "text": "",
        "preview": None,
    }


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Best-effort bounded termination of a child and its descendants."""

    if process.poll() is not None:
        return
    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if taskkill is not None:
            try:
                subprocess.run(
                    [taskkill, "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5.0,
                    check=False,
                    shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass


def run_bounded(
    argv: Sequence[str | os.PathLike[str]],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    stdin_bytes: bytes | None = None,
    cwd: str | os.PathLike[str] | None = None,
    env_overrides: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Run one direct child process with bounded time and retained output.

    The complete stdout/stderr streams are hashed, but only
    ``max_output_bytes`` from the beginning of each stream are retained.  No
    shell is involved.  A timeout proves only that this invocation exceeded its
    deadline; it makes no wider claim about the tool or platform.
    """

    command = _coerce_argv(argv)
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if max_output_bytes < 0:
        raise ValueError("max_output_bytes must not be negative")
    if stdin_bytes is not None and not isinstance(stdin_bytes, bytes):
        raise TypeError("stdin_bytes must be bytes or None")
    if stdin_bytes is not None and len(stdin_bytes) > DEFAULT_MAX_INPUT_BYTES:
        raise ValueError(
            f"stdin_bytes exceeds the {DEFAULT_MAX_INPUT_BYTES}-byte harness limit"
        )

    displayed_argv = [sanitize_text(item) for item in command]
    child_environment = None
    if env_overrides is not None:
        child_environment = os.environ.copy()
        child_environment.update({str(key): str(value) for key, value in env_overrides.items()})

    creation_flags = 0
    if os.name == "nt":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    started = time.perf_counter()
    try:
        process = subprocess.Popen(
            command,
            cwd=os.fspath(cwd) if cwd is not None else None,
            env=child_environment,
            stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=creation_flags,
            start_new_session=os.name != "nt",
        )
    except OSError as error:
        duration_ms = round((time.perf_counter() - started) * 1000)
        return {
            "argv": displayed_argv,
            "status": "spawn_error",
            "exit_code": None,
            "duration_ms": duration_ms,
            "timed_out": False,
            "stdout": _empty_stream_observation(),
            "stderr": _empty_stream_observation(),
            "error": sanitize_text(f"{type(error).__name__}: {error}"),
        }

    if process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise RuntimeError("subprocess pipes were not created")

    stdout_capture = _BoundedCapture(max_output_bytes)
    stderr_capture = _BoundedCapture(max_output_bytes)
    stdout_thread = threading.Thread(
        target=stdout_capture.drain,
        args=(process.stdout,),
        name="probe-stdout",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=stderr_capture.drain,
        args=(process.stderr,),
        name="probe-stderr",
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    stdin_writer: _BoundedInputWriter | None = None
    stdin_thread: threading.Thread | None = None
    if stdin_bytes is not None:
        if process.stdin is None:
            process.kill()
            process.wait()
            raise RuntimeError("subprocess stdin pipe was not created")
        stdin_writer = _BoundedInputWriter(stdin_bytes)
        stdin_thread = threading.Thread(
            target=stdin_writer.write,
            args=(process.stdin,),
            name="probe-stdin",
            daemon=True,
        )
        stdin_thread.start()

    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process)

    stdout_thread.join(timeout=1.0)
    stderr_thread.join(timeout=1.0)
    if stdin_thread is not None:
        stdin_thread.join(timeout=1.0)
    for thread, stream in (
        (stdout_thread, process.stdout),
        (stderr_thread, process.stderr),
    ):
        if thread.is_alive():
            try:
                stream.close()
            except (OSError, ValueError):
                pass
            thread.join(timeout=0.2)

    capture_complete = not stdout_thread.is_alive() and not stderr_thread.is_alive()
    input_complete = stdin_thread is None or not stdin_thread.is_alive()
    duration_ms = round((time.perf_counter() - started) * 1000)
    result: dict[str, object] = {
        "argv": displayed_argv,
        "cwd": sanitize_path(cwd) if cwd is not None else sanitize_path(Path.cwd()),
        "status": "timed_out" if timed_out else "completed",
        "exit_code": process.returncode,
        "duration_ms": duration_ms,
        "timed_out": timed_out,
        "capture_complete": capture_complete,
        "input_complete": input_complete,
        "stdout": stdout_capture.observation(),
        "stderr": stderr_capture.observation(),
    }
    if stdin_writer is not None:
        result["stdin"] = stdin_writer.observation()
    return result


def discover_executable(name: str) -> dict[str, object]:
    """Report discovery only; discovery does not prove successful execution."""

    if not name or any(character in name for character in ("\0", "\n", "\r")):
        raise ValueError("invalid executable name")
    resolved = shutil.which(name)
    return {
        "name": name,
        "available": resolved is not None,
        "path": sanitize_path(resolved) if resolved is not None else None,
    }


def collect_executable_facts(
    names: Iterable[str] = DEFAULT_EXECUTABLES,
) -> dict[str, dict[str, object]]:
    return {
        name: discover_executable(name)
        for name in sorted(set(names), key=lambda value: value.casefold())
    }


def _probe_command(name: str, arguments: Sequence[str]) -> dict[str, object]:
    discovery = discover_executable(name)
    if not discovery["available"]:
        return {
            "available": False,
            "discovery": discovery,
            "observation": None,
        }
    resolved = shutil.which(name)
    if resolved is None:
        raise AssertionError("executable disappeared after discovery")
    return {
        "available": True,
        "discovery": discovery,
        "observation": run_bounded([resolved, *arguments]),
    }


def _captured_text(result: dict[str, object] | None, stream: str = "stdout") -> str:
    if result is None:
        return ""
    observation = result.get(stream)
    if not isinstance(observation, dict):
        return ""
    text = observation.get("text")
    if isinstance(text, str):
        return text
    preview = observation.get("preview")
    return preview if isinstance(preview, str) else ""


def collect_rust_facts() -> dict[str, object]:
    rustc = _probe_command("rustc", ["-vV"])
    cargo = _probe_command("cargo", ["-V"])
    rustup_targets = _probe_command("rustup", ["target", "list", "--installed"])

    targets: list[str] = []
    target_observation = rustup_targets.get("observation")
    if isinstance(target_observation, dict):
        if (
            target_observation.get("status") == "completed"
            and target_observation.get("exit_code") == 0
        ):
            targets = sorted(
                line.strip()
                for line in _captured_text(target_observation).splitlines()
                if line.strip()
            )

    cargo_ndk_discovery = discover_executable("cargo-ndk")
    cargo_ndk_observation: dict[str, object] | None = None
    cargo_path = shutil.which("cargo")
    if cargo_ndk_discovery["available"] and cargo_path is not None:
        cargo_ndk_observation = run_bounded([cargo_path, "ndk", "--version"])

    return {
        "rustc": rustc,
        "cargo": cargo,
        "cargo_ndk": {
            "available": cargo_ndk_discovery["available"] and cargo_path is not None,
            "discovery": cargo_ndk_discovery,
            "observation": cargo_ndk_observation,
        },
        "rustup_targets": rustup_targets,
        "installed_targets": targets,
    }


def _read_properties(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    properties: dict[str, str] = {}
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key.strip()] = value.strip()
    return properties


def _package_fact(path: Path, sdk_root: Path) -> dict[str, object]:
    properties = _read_properties(path / "source.properties")
    return {
        "name": path.name,
        "version": properties.get("Pkg.Revision") or path.name,
        "path": sanitize_path(path, extra_roots=((sdk_root, "<ANDROID_SDK>"),)),
    }


def _versioned_packages(path: Path, sdk_root: Path) -> list[dict[str, object]]:
    if not path.is_dir():
        return []
    try:
        children = sorted(
            (
                child
                for child in path.iterdir()
                if child.is_dir() and not child.name.startswith(".")
            ),
            key=lambda child: child.name.casefold(),
        )
    except OSError:
        return []
    return [_package_fact(child, sdk_root) for child in children]


def _android_sdk_root() -> tuple[Path | None, str | None]:
    for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        value = os.environ.get(variable)
        if value:
            return Path(value), variable

    candidates: list[Path] = []
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "Android" / "Sdk")
    elif sys.platform == "darwin":
        candidates.append(Path.home() / "Library" / "Android" / "sdk")
    else:
        candidates.append(Path.home() / "Android" / "Sdk")

    for candidate in candidates:
        if candidate.is_dir():
            return candidate, "conventional_path"
    return None, None


def collect_android_facts() -> dict[str, object]:
    """Inspect installed SDK metadata without invoking SDK tools or devices."""

    sdk_root, source = _android_sdk_root()
    if sdk_root is None:
        return {
            "configured": False,
            "source": None,
            "sdk_root": None,
            "sdk_exists": False,
            "packages": {},
        }

    sdk_exists = sdk_root.is_dir()
    packages: dict[str, object] = {}
    if sdk_exists:
        packages = {
            "build_tools": _versioned_packages(sdk_root / "build-tools", sdk_root),
            "ndk": _versioned_packages(sdk_root / "ndk", sdk_root),
            "platforms": _versioned_packages(sdk_root / "platforms", sdk_root),
            "command_line_tools": _versioned_packages(
                sdk_root / "cmdline-tools", sdk_root
            ),
            "platform_tools": (
                _package_fact(sdk_root / "platform-tools", sdk_root)
                if (sdk_root / "platform-tools").is_dir()
                else None
            ),
            "emulator": (
                _package_fact(sdk_root / "emulator", sdk_root)
                if (sdk_root / "emulator").is_dir()
                else None
            ),
        }

    return {
        "configured": True,
        "source": source,
        "sdk_root": sanitize_path(
            sdk_root,
            extra_roots=((sdk_root, "<ANDROID_SDK>"),),
        ),
        "sdk_exists": sdk_exists,
        "packages": packages,
    }


def _windows_build_facts() -> dict[str, object] | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        registry_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path) as key:
            values: dict[str, object] = {}
            for name in (
                "ProductName",
                "DisplayVersion",
                "CurrentBuild",
                "CurrentBuildNumber",
                "UBR",
            ):
                try:
                    values[name] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    values[name] = None
        build = values.get("CurrentBuildNumber") or values.get("CurrentBuild")
        revision = values.get("UBR")
        values["full_build"] = (
            f"{build}.{revision}"
            if build is not None and revision is not None
            else str(build) if build is not None else None
        )
        return values
    except (OSError, ImportError):
        return None


def collect_host_facts() -> dict[str, object]:
    uname = platform.uname()
    return {
        "system": uname.system,
        "node": "<REDACTED>",
        "release": uname.release,
        "version": uname.version,
        "machine": uname.machine,
        "processor": uname.processor or platform.processor() or None,
        "architecture": platform.architecture()[0],
        "cpu_count": os.cpu_count(),
        "windows_build": _windows_build_facts(),
    }


def collect_python_facts() -> dict[str, object]:
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "version_info": list(sys.version_info[:5]),
        "version_string": sanitize_text(sys.version),
        "executable": sanitize_path(sys.executable),
        "sqlite_version": sqlite3.sqlite_version,
        "sqlite_version_info": list(sqlite3.sqlite_version_info),
        "sqlite_threadsafety": sqlite3.threadsafety,
    }


def collect_environment(
    executable_names: Iterable[str] = DEFAULT_EXECUTABLES,
) -> dict[str, object]:
    """Collect facts without claiming that any target can build or execute."""

    return {
        "schema_version": 1,
        "host": collect_host_facts(),
        "python": collect_python_facts(),
        "executables": collect_executable_facts(executable_names),
        "rust": collect_rust_facts(),
        "android": collect_android_facts(),
    }


class _SelfTests(unittest.TestCase):
    def test_sanitize_path_hides_home(self) -> None:
        raw = str(Path.home() / "private" / "probe.txt")
        sanitized = sanitize_path(raw)
        self.assertIn("<HOME>", sanitized)
        self.assertNotIn(
            os.path.normcase(str(Path.home())),
            os.path.normcase(sanitized),
        )

    def test_byte_and_file_fingerprints(self) -> None:
        self.assertEqual(
            sha256_bytes(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        fact = file_fingerprint(__file__)
        self.assertEqual(fact["size_bytes"], Path(__file__).stat().st_size)
        self.assertEqual(len(str(fact["sha256"])), 64)

    def test_direct_process_captures_exit_and_streams(self) -> None:
        result = run_bounded(
            [
                sys.executable,
                "-c",
                (
                    "import sys;"
                    "sys.stdout.write('stdout');"
                    "sys.stderr.write('stderr');"
                    "raise SystemExit(3)"
                ),
            ]
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["exit_code"], 3)
        self.assertEqual(result["stdout"]["text"], "stdout")  # type: ignore[index]
        self.assertEqual(result["stderr"]["text"], "stderr")  # type: ignore[index]

    def test_capture_is_truncated_but_fully_hashed(self) -> None:
        payload = b"x" * 128
        result = run_bounded(
            [sys.executable, "-c", "import sys;sys.stdout.write('x'*128)"],
            max_output_bytes=16,
        )
        stdout = result["stdout"]
        self.assertEqual(stdout["size_bytes"], 128)  # type: ignore[index]
        self.assertTrue(stdout["truncated"])  # type: ignore[index]
        self.assertIsNone(stdout["text"])  # type: ignore[index]
        self.assertEqual(stdout["preview"], "x" * 16)  # type: ignore[index]
        self.assertEqual(stdout["sha256"], sha256_bytes(payload))  # type: ignore[index]

    def test_timeout_is_reported_without_support_claim(self) -> None:
        result = run_bounded(
            [sys.executable, "-c", "import time;time.sleep(2)"],
            timeout_seconds=0.1,
        )
        self.assertEqual(result["status"], "timed_out")
        self.assertTrue(result["timed_out"])
        self.assertIsInstance(result["duration_ms"], int)

    def test_direct_process_accepts_bounded_stdin(self) -> None:
        result = run_bounded(
            [
                sys.executable,
                "-c",
                "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read()[::-1])",
            ],
            stdin_bytes=b"abc",
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"]["text"], "cba")  # type: ignore[index]
        self.assertEqual(result["stdin"]["size_bytes"], 3)  # type: ignore[index]
        self.assertEqual(result["stdin"]["sha256"], sha256_bytes(b"abc"))  # type: ignore[index]

    def test_shell_command_string_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            run_bounded("echo unsafe")  # type: ignore[arg-type]

    def test_android_root_is_sanitized_when_configured(self) -> None:
        facts = collect_android_facts()
        sdk_root, _ = _android_sdk_root()
        if sdk_root is not None:
            rendered = json.dumps(facts, sort_keys=True)
            self.assertNotIn(
                os.path.normcase(str(sdk_root)),
                os.path.normcase(rendered),
            )


def _run_self_tests() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(_SelfTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)

    if arguments.self_test:
        return _run_self_tests()
    print(json.dumps(collect_environment(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
