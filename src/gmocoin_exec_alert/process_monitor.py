from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .pagerduty import PagerDutyClient


@dataclass
class ProcessInfo:
    pid: int
    command: str
    start_time: str


class ProcessMonitor:
    """Monitor 'uv run atc' processes and notify when they complete."""

    def __init__(
        self,
        *,
        pattern: str = r"uv run atc",
        check_interval_sec: int = 5,
        idle_threshold_sec: int = 60,
        logger: logging.Logger | None = None,
    ) -> None:
        self._pattern = re.compile(pattern)
        self._check_interval_sec = check_interval_sec
        self._idle_threshold_sec = idle_threshold_sec
        self._logger = logger or logging.getLogger(__name__)
        self._last_seen_time: datetime | None = None
        self._has_notified = False
        # Use a stable dedup_key so we can resolve the same incident
        self._dedup_key = "ml-job-monitoring"

    def _find_matching_processes(self) -> list[ProcessInfo]:
        """Find all processes matching the pattern using ps command."""
        try:
            # Use ps to find processes
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                check=True,
            )

            processes = []
            for line in result.stdout.splitlines():
                if self._pattern.search(line):
                    # Parse ps output
                    parts = line.split(None, 10)
                    if len(parts) >= 11:
                        try:
                            pid = int(parts[1])
                            # Get process start time and command
                            start_time = parts[8]  # START column
                            command = parts[10]    # COMMAND column
                            processes.append(ProcessInfo(
                                pid=pid,
                                command=command,
                                start_time=start_time,
                            ))
                        except (ValueError, IndexError):
                            continue

            return processes
        except subprocess.CalledProcessError as e:
            self._logger.error("Failed to run ps command: %s", e)
            return []
        except Exception as e:
            self._logger.error("Error finding processes: %s", e)
            return []

    async def monitor_loop(
        self,
        *,
        stop: asyncio.Event,
        pd: PagerDutyClient,
    ) -> None:
        """
        Main monitoring loop.

        Continuously checks for processes matching the pattern.
        When processes are found, tracks them.
        When all processes are gone for idle_threshold_sec, sends PagerDuty notification.
        """
        self._logger.info(
            "Starting process monitor (pattern=%s, check_interval=%ds, idle_threshold=%ds)",
            self._pattern.pattern,
            self._check_interval_sec,
            self._idle_threshold_sec,
        )

        while not stop.is_set():
            try:
                # Wait for check interval
                await asyncio.wait_for(stop.wait(), timeout=self._check_interval_sec)
                return
            except TimeoutError:
                pass

            # Find matching processes
            processes = self._find_matching_processes()
            now = datetime.now()

            if processes:
                # Processes are running
                if self._last_seen_time is None:
                    self._logger.info("Detected matching process(es). Monitoring for completion...")
                    # If we previously notified about completion, resolve the incident
                    if self._has_notified:
                        await self._resolve_incident(pd)
                        self._has_notified = False
                self._last_seen_time = now
                self._logger.debug(
                    "Found %d matching process(es): %s",
                    len(processes),
                    [p.command for p in processes],
                )
            else:
                # No processes found
                if self._last_seen_time is not None:
                    # We have seen processes before
                    idle_duration = (now - self._last_seen_time).total_seconds()

                    if idle_duration >= self._idle_threshold_sec and not self._has_notified:
                        # Threshold exceeded, send notification
                        await self._send_completion_notification(pd)
                        self._has_notified = True
                        # Reset state
                        self._last_seen_time = None

    async def _send_completion_notification(self, pd: PagerDutyClient) -> None:
        """Send PagerDuty notification that ML job has completed."""
        summary = (
            f"ML Job Completed: No '{self._pattern.pattern}' processes detected for "
            f"{self._idle_threshold_sec} seconds"
        )
        custom_details: dict[str, Any] = {
            "event_type": "ml_job_completion",
            "pattern": self._pattern.pattern,
            "idle_threshold_sec": self._idle_threshold_sec,
            "completion_time": datetime.now().isoformat(),
        }

        try:
            await pd.trigger(
                dedup_key=self._dedup_key,
                summary=summary,
                custom_details=custom_details,
            )
            self._logger.info("PagerDuty notification sent: %s", summary)
        except Exception as e:
            self._logger.exception("Failed to send PagerDuty notification: %s", e)
            raise

    async def _resolve_incident(self, pd: PagerDutyClient) -> None:
        """Resolve the PagerDuty incident when processes restart."""
        try:
            await pd.resolve(dedup_key=self._dedup_key)
            self._logger.info(
                "PagerDuty incident resolved: ML job processes have restarted"
            )
        except Exception as e:
            self._logger.exception("Failed to resolve PagerDuty incident: %s", e)
            # Don't raise here - we still want to continue monitoring