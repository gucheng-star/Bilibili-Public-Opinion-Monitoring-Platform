"""Windows smoke test for the final portable desktop EXE MCP stdio mode."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass

from mcp import Client, StdioServerParameters


EXPECTED_TOOLS = {
    "bili_list_analyses",
    "bili_get_analysis_overview",
    "bili_search_comments",
}
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
SESSION_PREFIX = "mcp-session-"
TIMEOUT_SECONDS = 30


@dataclass
class SmokeCounts:
    sessions: int = 0
    tools: int = 0
    list_calls: int = 0
    overview_calls: int = 0
    search_calls: int = 0
    active_directories: int = 0
    residual_directories: int = 0
    sidecars: int = 0


class SafeArgumentParser(argparse.ArgumentParser):
    """Avoid echoing command-line input in a CI failure message."""

    def error(self, _message: str) -> None:
        raise ValueError("Invalid smoke-test arguments")


def parse_arguments() -> argparse.Namespace:
    parser = SafeArgumentParser(add_help=False)
    parser.add_argument("executable", type=Path, help="Path to the final desktop EXE")
    return parser.parse_args()


def create_fixture(database_path: Path) -> None:
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE analyses (
                id INTEGER PRIMARY KEY,
                bv TEXT NOT NULL,
                video_title TEXT,
                video_cover TEXT,
                status TEXT,
                mode TEXT,
                total_comments INTEGER,
                created_at TEXT,
                error_msg TEXT
            );
            CREATE TABLE comments (
                id INTEGER PRIMARY KEY,
                analysis_id INTEGER NOT NULL,
                rpid INTEGER,
                root_rpid INTEGER,
                parent_rpid INTEGER,
                username TEXT,
                gender TEXT,
                ip_location TEXT,
                content TEXT,
                likes INTEGER,
                sentiment_label TEXT,
                sentiment_llm_label TEXT,
                post_time TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO analyses VALUES (?,?,?,?,?,?,?,?,?)",
            (1, "BV1SMOKE", "fixture", "", "done", "nlp", 2, "2026-08-30T00:00:00", ""),
        )
        connection.executemany(
            "INSERT INTO comments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (1, 1, 1, None, None, "", "", "", "fixture-keyword", 1, "positive", "", "2026-08-30T00:00:01"),
                (2, 1, 2, None, None, "", "", "", "fixture-keyword", 0, "neutral", "", "2026-08-30T00:00:02"),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_entries(path: Path) -> set[str]:
    if not path.exists():
        return set()
    if not path.is_dir():
        raise RuntimeError("MCP temporary root is not a directory")
    return {entry.name for entry in path.iterdir()}


def sidecar_count(database_path: Path) -> int:
    return sum(Path(f"{database_path}{suffix}").exists() for suffix in SIDECAR_SUFFIXES)


async def exercise_session(
    executable: Path,
    environment: dict[str, str],
    ready: asyncio.Event,
    release: asyncio.Event,
    counts: SmokeCounts,
) -> None:
    parameters = StdioServerParameters(
        command=str(executable),
        args=["--mcp-stdio"],
        env=environment,
        cwd=str(executable.parent),
    )
    async with Client(parameters, read_timeout_seconds=TIMEOUT_SECONDS) as client:
        listed_tools = await client.list_tools()
        tools = {tool.name for tool in listed_tools.tools}
        if tools != EXPECTED_TOOLS:
            raise RuntimeError("Unexpected MCP tool set")
        counts.tools = len(tools)

        listed = await client.call_tool("bili_list_analyses", {"limit": 1})
        overview = await client.call_tool("bili_get_analysis_overview", {"analysis_id": 1})
        searched = await client.call_tool(
            "bili_search_comments",
            {"analysis_id": 1, "keyword": "fixture-keyword", "limit": 1},
        )
        if listed.is_error or overview.is_error or searched.is_error:
            raise RuntimeError("Required MCP tool call failed")
        if listed.structured_content["total_count"] != 1:
            raise RuntimeError("Fixture list result did not match")
        if overview.structured_content["sentiment_denominator"] != 2:
            raise RuntimeError("Fixture overview result did not match")
        if searched.structured_content["returned_count"] != 1:
            raise RuntimeError("Fixture search result did not match")

        counts.sessions += 1
        counts.list_calls += 1
        counts.overview_calls += 1
        counts.search_calls += 1
        ready.set()
        await release.wait()


async def run_smoke(executable: Path, database_path: Path, counts: SmokeCounts) -> None:
    temporary_root = executable.parent / "data" / "runtime" / "mcp-tmp"
    baseline = directory_entries(temporary_root)
    environment = dict(os.environ)
    environment["BILI_MCP_DB_PATH"] = str(database_path)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    ready = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()
    tasks = [
        asyncio.create_task(exercise_session(executable, environment, event, release, counts))
        for event in ready
    ]
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready)), timeout=TIMEOUT_SECONDS)
        current_entries = directory_entries(temporary_root)
        new_directories = [
            temporary_root / name
            for name in current_entries - baseline
            if name.startswith(SESSION_PREFIX) and (temporary_root / name).is_dir()
        ]
        if len(new_directories) != 2 or len({directory.name for directory in new_directories}) != 2:
            raise RuntimeError("Concurrent MCP session directories were not observed")
        counts.active_directories = len(new_directories)
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        if any(isinstance(result, BaseException) for result in results):
            raise RuntimeError("MCP session execution failed")

    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        remaining = directory_entries(temporary_root) - baseline
        if not remaining:
            break
        await asyncio.sleep(0.1)
    residual = directory_entries(temporary_root) - baseline
    counts.residual_directories = len(residual)
    if residual:
        raise RuntimeError("MCP session temporary files remain after EOF")


def print_result(prefix: str, counts: SmokeCounts, stream: object = sys.stdout) -> None:
    print(
        f"{prefix}: sessions={counts.sessions} tools={counts.tools} "
        f"list_calls={counts.list_calls} overview_calls={counts.overview_calls} "
        f"search_calls={counts.search_calls} active_directories={counts.active_directories} "
        f"residual_directories={counts.residual_directories} sidecars={counts.sidecars}",
        file=stream,
    )


def main() -> int:
    counts = SmokeCounts()
    try:
        if os.name != "nt":
            raise RuntimeError("Windows is required")
        executable = parse_arguments().executable.resolve(strict=True)
        if executable.suffix.casefold() != ".exe" or not executable.is_file():
            raise RuntimeError("Final desktop executable is unavailable")
        with tempfile.TemporaryDirectory(prefix="bili-mcp-smoke-") as temporary:
            database_path = Path(temporary) / "fixture.sqlite3"
            create_fixture(database_path)
            before_hash = sha256(database_path)
            try:
                asyncio.run(run_smoke(executable, database_path, counts))
            finally:
                after_hash = sha256(database_path)
                counts.sidecars = sidecar_count(database_path)
            if before_hash != after_hash or counts.sidecars:
                raise RuntimeError("Fixture database changed during MCP smoke test")
        print_result("MCP smoke passed", counts)
        return 0
    except Exception:
        print_result("MCP smoke failed", counts, stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
