"""Small, explicit Docker observations retained before a run container is removed.

An exit status of 137 is not an OOM diagnosis.  Only Docker's OOMKilled flag is
reported as confirmed OOM; missing observations remain unknown.  This module
never reads container environment variables, mount paths or full Docker info.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Any

from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.tracking import utc_now
from nipat.execution.transport import cleanup_process_options


_ID = re.compile(r"[0-9a-f]{64}\Z")
_INSPECT_FORMAT = (
    '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},'
    '"labels":{{json .Config.Labels}},'
    '"state":{"status":{{json .State.Status}},"oom_killed":{{json .State.OOMKilled}},'
    '"exit_code":{{json .State.ExitCode}},"started_at":{{json .State.StartedAt}},'
    '"finished_at":{{json .State.FinishedAt}}},'
    '"limits":{"memory_bytes":{{json .HostConfig.Memory}},'
    '"memory_swap_bytes":{{json .HostConfig.MemorySwap}},'
    '"nano_cpus":{{json .HostConfig.NanoCpus}},"cpu_period":{{json .HostConfig.CpuPeriod}},'
    '"cpu_quota":{{json .HostConfig.CpuQuota}},"pids_limit":{{json .HostConfig.PidsLimit}}}}'
)


def inspect_container(runner, name: str, expected_labels: dict[str, str], *,
                      timeout: float = 15) -> dict[str, Any]:
    observation: dict[str, Any] = {
        "observed_at": utc_now(), "availability": "unavailable", "owned": False,
    }
    try:
        argv = runner._transport.command(
            ["docker", "container", "inspect", name, "--format", _INSPECT_FORMAT],
            runner._environment(),
        )
        result = subprocess.run(
            argv, env=runner._environment(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
            stdin=subprocess.DEVNULL, **cleanup_process_options(),
        )
        if result.returncode:
            missing = any(text in result.stderr.lower()
                          for text in ("no such container", "no such object"))
            observation["availability"] = "absent" if missing else "unavailable"
            observation["reason"] = "container_not_found" if missing else "inspect_failed"
            return observation
        # A bounded, allowlisted response cannot accidentally persist Docker's
        # environment, credentials or metadata belonging to unrelated containers.
        if len(result.stdout) > 64 * 1024:
            raise ValueError("oversized inspect response")
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError("invalid inspect response")
        identifier = value.get("id")
        labels = value.get("labels")
        expected_image = runner._image_id
        owned = (
            isinstance(identifier, str) and _ID.fullmatch(identifier) is not None
            and value.get("name") == "/" + name
            and isinstance(labels, dict) and bool(expected_labels)
            and all(labels.get(key) == expected for key, expected in expected_labels.items())
            and (expected_image is None or value.get("image") == expected_image)
        )
        if not owned:
            observation.update(availability="identity_mismatch", reason="ownership_not_verified")
            return observation
        state, limits = value.get("state"), value.get("limits")
        if (not isinstance(state, dict) or not isinstance(limits, dict)
                or state.get("status") not in {"created", "running", "paused", "restarting", "removing", "exited", "dead"}
                or type(state.get("oom_killed")) is not bool
                or type(state.get("exit_code")) is not int
                or any(not isinstance(state.get(key), str) or len(state[key]) > 128
                       for key in ("started_at", "finished_at"))
                or any(type(limits.get(key)) is not int for key in
                       ("memory_bytes", "memory_swap_bytes", "nano_cpus", "cpu_period", "cpu_quota"))
                or (limits.get("pids_limit") is not None and type(limits["pids_limit"]) is not int)):
            raise ValueError("invalid state or resource limits")
        observation.update(
            availability="available", owned=True, container_id=identifier,
            state={key: state[key] for key in
                   ("status", "oom_killed", "exit_code", "started_at", "finished_at")},
            limits={key: limits.get(key) for key in
                    ("memory_bytes", "memory_swap_bytes", "nano_cpus", "cpu_period", "cpu_quota", "pids_limit")},
        )
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, RecursionError,
            RuntimeExecutionError, ValidationError):
        observation["reason"] = "observation_unavailable"
    return observation


def settle_oom_observation(runner, name: str, expected_labels: dict[str, str],
                           observation: dict[str, Any], returncode: int | None) -> dict[str, Any]:
    """Briefly recheck a terminal SIGKILL before removing its owned container.

    Docker may deliver an OOM flag after the exit notification. Never infer it
    from 137 or replace a verified observation with unavailable/replaced state.
    The five attempts share a two-second budget, including inspection timeouts.
    """
    state = observation.get("state", {})
    identifier = observation.get("container_id", "")
    if (returncode not in (137, -9) or observation.get("owned") is not True
            or observation.get("availability") != "available"
            or state.get("status") not in {"exited", "dead"}
            or state.get("oom_killed") is not False
            or not isinstance(identifier, str) or not _ID.fullmatch(identifier)):
        return observation
    deadline = time.monotonic() + 2.0
    for _ in range(5):
        if deadline - time.monotonic() <= 0.2:
            break
        time.sleep(0.2)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        updated = inspect_container(runner, name, expected_labels, timeout=remaining)
        if (updated.get("owned") is not True or updated.get("container_id") != identifier
                or updated.get("state", {}).get("status") not in {"exited", "dead"}):
            break
        observation = updated
        if updated["state"].get("oom_killed") is True:
            break
    return observation


def diagnose(observation: dict[str, Any], returncode: int | None, *, interrupted: bool) -> dict[str, str]:
    if interrupted:
        return {"kind": "interrupted", "message": "Esecuzione annullata dall'utente."}
    state = observation.get("state", {})
    if observation.get("owned") is True and state.get("oom_killed") is True:
        return {
            "kind": "oom_confirmed",
            "message": "Docker ha registrato una terminazione per memoria insufficiente. "
                       "Verificare la memoria disponibile nell'ambiente di analisi e il limite "
                       "del container; la modalita parallela puo richiedere piu memoria.",
        }
    if returncode in (137, -9):
        return {
            "kind": "sigkill_unconfirmed",
            "message": "Il codice di uscita e compatibile con una terminazione forzata (SIGKILL). "
                       "La memoria insufficiente e una possibile causa, ma non e confermata "
                       "dalle informazioni disponibili. Consultare execution.log e run.json.",
        }
    return {"kind": "completed" if returncode == 0 else "failed",
            "message": "Esecuzione completata." if returncode == 0 else
                       "Il comando non e stato completato; consultare execution.log."}
