"""Dedicated YAML-driven static-web authoring mode.

Implemented:
    Strict, bounded YAML input.
    Project-relative write/delete/image commands.
    Per-iteration filesystem checkpoints.
    Local static serving and Playwright diagnostics.
    Final viewport screenshot and provider-based visual review.
    Persistent task budgets and JSON diagnostic artifacts.

MVP constraints:
    One task runner at a time per state directory.
    Chromium only.
    Browser sessions are recreated for each iteration.
    Remote resource requests are blocked.
    Checkpoints are full copies, not Git commits.
    File replacement is atomic per file, not across the whole command batch.
    Deadlines are cooperative, not process-level hard limits.

Future extension points:
    Patch commands, checkpoint restoration, multiple viewports/pages,
    accessibility audits, visual baselines, provider cancellation, streaming
    events, shared planner accounting, and a persistent browser service.

This is not a security sandbox. Only run trusted generated JavaScript.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import io
import json
import math
import os
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml
from jsonschema import Draft202012Validator
from PIL import Image
from playwright.async_api import async_playwright

from providers import (
    GeneratedImage,
    GenerationRequest,
    NotConfigured,
    Providers,
    ReviewRequest,
    VisualReview,
)


# ---------- Authoring document schema ----------

def object_schema(
    properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    """Construct a closed JSON-schema object."""
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


STRING = {"type": "string", "maxLength": 200_000}
PATH = {"type": "string", "minLength": 1, "maxLength": 512}
SELECTOR = {"type": "string", "minLength": 1, "maxLength": 1_000}
DIMENSION = {"type": "integer", "minimum": 1, "maximum": 4096}

COMMAND_SCHEMA = {
    "oneOf": [
        object_schema(
            {
                "op": {"const": "write"},
                "path": PATH,
                "content": STRING,
            },
            ["op", "path", "content"],
        ),
        object_schema(
            {"op": {"const": "delete"}, "path": PATH},
            ["op", "path"],
        ),
        object_schema(
            {
                "op": {"const": "generate_image"},
                "path": PATH,
                "prompt": STRING,
                "width": DIMENSION,
                "height": DIMENSION,
            },
            ["op", "path", "prompt", "width", "height"],
        ),
    ]
}

INTERACTION_SCHEMA = {
    "oneOf": [
        object_schema(
            {
                "action": {"enum": ["click", "assert_visible"]},
                "selector": SELECTOR,
            },
            ["action", "selector"],
        ),
        object_schema(
            {
                "action": {"const": "fill"},
                "selector": SELECTOR,
                "value": STRING,
            },
            ["action", "selector", "value"],
        ),
        object_schema(
            {
                "action": {"const": "press"},
                "selector": SELECTOR,
                "key": {"type": "string", "maxLength": 100},
            },
            ["action", "selector", "key"],
        ),
        object_schema(
            {
                "action": {"const": "assert_text"},
                "selector": SELECTOR,
                "equals": STRING,
            },
            ["action", "selector", "equals"],
        ),
        object_schema(
            {
                "action": {"const": "scroll"},
                "x": {
                    "type": "integer",
                    "minimum": -100_000,
                    "maximum": 100_000,
                },
                "y": {
                    "type": "integer",
                    "minimum": -100_000,
                    "maximum": 100_000,
                },
            },
            ["action", "x", "y"],
        ),
    ]
}

DOCUMENT_SCHEMA = object_schema(
    {
        "version": {"const": 1},
        "commands": {
            "type": "array",
            "maxItems": 100,
            "items": COMMAND_SCHEMA,
        },
        "check": object_schema(
            {
                "page": PATH,
                "viewport": object_schema(
                    {"width": DIMENSION, "height": DIMENSION},
                    ["width", "height"],
                ),
                "interactions": {
                    "type": "array",
                    "maxItems": 50,
                    "items": INTERACTION_SCHEMA,
                },
                "visual_expectations": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 20_000,
                },
            },
            ["page", "visual_expectations"],
        ),
    },
    ["version", "commands", "check"],
)


class StrictLoader(yaml.SafeLoader):
    """Safe YAML loader rejecting duplicate or non-string mapping keys."""


def strict_mapping(
    loader: StrictLoader, node: yaml.MappingNode
) -> dict[str, Any]:
    """Prevent duplicate keys from silently changing authoring intent."""
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str):
            raise ValueError("YAML mapping keys must be strings.")
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node)
    return result


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    strict_mapping,
)


def parse_document(text: str) -> dict[str, Any]:
    """Parse a bounded YAML document without aliases, anchors, or custom tags."""
    if len(text.encode("utf-8")) > 2_000_000:
        raise ValueError("Authoring document exceeds 2 MB.")

    depth = 0
    for event in yaml.parse(text):
        if isinstance(
            event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)
        ):
            depth += 1
            if depth > 30:
                raise ValueError("YAML nesting is too deep.")
        if isinstance(
            event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)
        ):
            depth -= 1
        if isinstance(event, yaml.AliasEvent):
            raise ValueError("YAML aliases are not allowed.")
        if getattr(event, "anchor", None):
            raise ValueError("YAML anchors are not allowed.")
        if getattr(event, "tag", None):
            raise ValueError("Explicit YAML tags are not allowed.")

    document = yaml.load(text, Loader=StrictLoader)
    Draft202012Validator(DOCUMENT_SCHEMA).validate(document)
    return document


# ---------- Workspace and persistence ----------

def safe_path(root: Path, relative: str) -> Path:
    """Resolve an ordinary relative path without traversing symlinks.

    This is defense against accidental path escape, not a race-proof sandbox.
    """
    if "\\" in relative or ":" in relative:
        raise ValueError(f"Unsupported path: {relative}")
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {".", ".."} or part.startswith(".")
               for part in path.parts)
    ):
        raise ValueError(f"Unsafe project path: {relative}")

    candidate = root
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(f"Symlink paths are forbidden: {relative}")

    candidate.resolve().relative_to(root.resolve())
    return candidate


def atomic_write(path: Path, data: bytes) -> None:
    """Replace one file atomically, creating its parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=".workbench-"
    )
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, value: Any) -> None:
    """Persist JSON-safe state without allowing NaN or infinity."""
    atomic_write(
        path,
        json.dumps(value, indent=2, allow_nan=False).encode("utf-8"),
    )


@contextmanager
def task_lock(state: Path):
    """Reject concurrent writers to this task.

    An interrupted process can leave the lock file behind. Remove it manually
    only after confirming that no runner is still using the task.
    """
    lock = state / "runner.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


class BudgetExceeded(RuntimeError):
    """A task cannot authorize another iteration or provider call."""


@dataclass(frozen=True)
class Policy:
    """Host-controlled task limits; never supplied by the authoring YAML.

    Elapsed time is measured from the first accepted iteration and includes
    time between turns. Provider reservations are conservative estimates unless
    the configured provider offers a genuine upper bound.
    """

    max_iterations: int = 10
    max_elapsed_seconds: float = 900
    max_cost_usd: float = 2.0
    review_reservation_usd: float = 0.10
    generation_reservation_usd: float = 0.50
    action_timeout_ms: int = 5_000

    def __post_init__(self):
        """Reject unusable or non-finite policy values."""
        if self.max_iterations < 1 or self.action_timeout_ms < 1:
            raise ValueError("Iteration and action limits must be positive.")
        for name in (
            "max_elapsed_seconds",
            "max_cost_usd",
            "review_reservation_usd",
            "generation_reservation_usd",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive.")


class Ledger:
    """Persistent, single-writer task accounting.

    A reservation is persisted before making a billable call. Failed calls or
    unknown prices retain their full reservation rather than becoming free.

    Future:
        Replace this with an adapter to the planner's shared ledger. Authoring
        LLM calls are outside this local ledger and must be charged by the host.
    """

    def __init__(self, state: Path, policy: Policy):
        """Load a task ledger and prevent accidental policy replacement."""
        self.path = state / "ledger.json"
        self.policy = policy
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            if self.data["policy"] != asdict(policy):
                raise ValueError(
                    "Existing task policy differs; use the original policy "
                    "or explicitly create a new task state directory."
                )
        else:
            self.data = {
                "policy": asdict(policy),
                "started_at": None,
                "iterations": 0,
                "calls": [],
            }

    def save(self) -> None:
        """Persist accounting before exposing its effects externally."""
        write_json(self.path, self.data)

    def remaining_seconds(self) -> float:
        """Return the remaining wall-clock task allowance."""
        started = self.data["started_at"]
        if started is None:
            return self.policy.max_elapsed_seconds
        return self.policy.max_elapsed_seconds - (time.time() - started)

    def charged_or_reserved(self) -> float:
        """Count unknown-cost calls at their reserved amount."""
        return sum(
            call["actual_cost_usd"]
            if call["actual_cost_usd"] is not None
            else call["reserved_usd"]
            for call in self.data["calls"]
        )

    def begin_iteration(self) -> int:
        """Authorize and persist one iteration."""
        if self.remaining_seconds() <= 0:
            raise BudgetExceeded("Elapsed-time budget exhausted.")
        if self.data["iterations"] >= self.policy.max_iterations:
            raise BudgetExceeded("Iteration budget exhausted.")
        if self.charged_or_reserved() >= self.policy.max_cost_usd:
            raise BudgetExceeded("Monetary budget exhausted.")

        if self.data["started_at"] is None:
            self.data["started_at"] = time.time()
        self.data["iterations"] += 1
        self.save()
        return self.data["iterations"]

    def reserve(self, kind: str, amount: float) -> int:
        """Reserve a provider-call allowance before starting the call."""
        if self.remaining_seconds() <= 0:
            raise BudgetExceeded("Elapsed-time budget exhausted.")
        if self.charged_or_reserved() + amount > self.policy.max_cost_usd:
            raise BudgetExceeded(f"Insufficient budget for {kind}.")
        self.data["calls"].append(
            {
                "kind": kind,
                "iteration": self.data["iterations"],
                "reserved_usd": amount,
                "actual_cost_usd": None,
                "status": "reserved",
            }
        )
        self.save()
        return len(self.data["calls"]) - 1

    def settle(self, call_id: int, actual: float | None) -> None:
        """Record reported cost, preserving reservations when cost is unknown.

        An overrun is recorded before raising: external charges cannot be
        undone by this ledger.
        """
        if actual is not None and (
            not math.isfinite(actual) or actual < 0
        ):
            raise ValueError("Provider returned an invalid cost.")

        call = self.data["calls"][call_id]
        call["actual_cost_usd"] = actual
        call["status"] = (
            "completed" if actual is not None else "cost_unknown"
        )
        self.save()

        if actual is not None and actual > call["reserved_usd"]:
            raise BudgetExceeded(
                "Provider exceeded its reservation; actual cost recorded."
            )

    def summary(self) -> dict[str, Any]:
        """Return bounded accounting data for an iteration report."""
        return {
            "iterations": self.data["iterations"],
            "elapsed_seconds": (
                0 if self.data["started_at"] is None
                else max(0, time.time() - self.data["started_at"])
            ),
            "charged_or_reserved_usd": self.charged_or_reserved(),
            "unknown_cost_calls": sum(
                call["actual_cost_usd"] is None
                for call in self.data["calls"]
            ),
        }


# ---------- Local preview ----------

class PreviewHandler(SimpleHTTPRequestHandler):
    """Serve project files without directory listings or symlink traversal."""

    def log_message(self, format: str, *args: Any) -> None:
        """Keep HTTP access logs out of the JSON command-line output."""

    def list_directory(self, path: str):
        """Disable directory listings."""
        self.send_error(403, "Directory listings are disabled.")
        return None

    def send_head(self):
        """Check the requested path before delegating static-file serving."""
        try:
            relative = unquote(urlsplit(self.path).path).lstrip("/")
            relative = relative or "index.html"
            root = Path(self.directory).resolve()
            target = safe_path(root, relative)
            if target.is_dir():
                safe_path(root, f"{relative.rstrip('/')}/index.html")
                safe_path(root, f"{relative.rstrip('/')}/index.htm")
        except (ValueError, OSError):
            self.send_error(403, "Forbidden path.")
            return None
        return super().send_head()


@contextmanager
def preview_server(root: Path):
    """Start a temporary loopback-only static server for one diagnostic run."""
    handler = partial(PreviewHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(
        target=server.serve_forever, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


# ---------- Authoring execution ----------

class Workbench:
    """Apply one authoring response and automatically diagnose the result."""

    def __init__(
        self,
        project: Path,
        state: Path,
        *,
        policy: Policy | None = None,
        providers: Providers | None = None,
    ):
        """Set host-controlled directories, providers, and limits.

        State must be outside the project so checkpoints, ledgers, and
        screenshots cannot be served as project assets.
        """
        self.project = project.resolve()
        self.state = state.resolve()
        if (
            self.project == self.state
            or self.project in self.state.parents
            or self.state in self.project.parents
        ):
            raise ValueError("Project and state directories must be separate.")
        self.project.mkdir(parents=True, exist_ok=True)
        self.state.mkdir(parents=True, exist_ok=True)
        self.policy = policy or Policy()
        self.providers = providers or Providers()

    async def run(self, text: str) -> dict[str, Any]:
        """Execute a bounded iteration and persist its diagnostic report.

        Invalid authoring input does not consume an iteration. Accepted input
        does, even if application, browsing, or review subsequently fails.
        """
        try:
            document = parse_document(text)
            for command in document["commands"]:
                target = safe_path(self.project, command["path"])
                if command["op"] == "generate_image":
                    if target.suffix.lower() != ".png":
                        raise ValueError(
                            "Generated image destinations must end in .png."
                        )
            safe_path(self.project, document["check"]["page"])
        except Exception as exc:
            return {
                "status": "invalid_input",
                "errors": [str(exc)[:4_000]],
            }

        try:
            with task_lock(self.state):
                return await self._run_locked(document)
        except FileExistsError:
            return {
                "status": "busy",
                "errors": ["Another runner holds this task's lock."],
            }

    async def _run_locked(
        self, document: dict[str, Any]
    ) -> dict[str, Any]:
        """Run one iteration while exclusively owning the task ledger."""
        try:
            ledger = Ledger(self.state, self.policy)
            iteration = ledger.begin_iteration()
        except (BudgetExceeded, ValueError) as exc:
            return {"status": "blocked", "errors": [str(exc)]}

        artifacts = self.state / "iterations" / f"{iteration:04d}"
        artifacts.mkdir(parents=True, exist_ok=False)

        report: dict[str, Any] = {
            "iteration": iteration,
            "status": "running",
            "checkpoint": None,
            "applied_commands": [],
            "errors": [],
            "warnings": [],
            "interactions": [],
            "screenshot": None,
            "visual_review": None,
            "review_status": "pending",
        }

        try:
            await asyncio.wait_for(
                self._execute(document, ledger, artifacts, report),
                timeout=max(0.001, ledger.remaining_seconds()),
            )
        except asyncio.TimeoutError:
            report["errors"].append("Task elapsed-time budget exhausted.")
        except Exception as exc:
            report["errors"].append(str(exc)[:4_000])

        if report["errors"]:
            report["status"] = "needs_attention"
        elif report["review_status"] != "completed":
            report["status"] = "incomplete"
        else:
            review = report["visual_review"]
            report["status"] = (
                "passed"
                if review["passed"] and not review["uncertainties"]
                else "needs_attention"
            )

        report["accounting"] = ledger.summary()
        report["report_path"] = str(artifacts / "report.json")
        write_json(artifacts / "report.json", report)
        return report

    async def _execute(
        self,
        document: dict[str, Any],
        ledger: Ledger,
        artifacts: Path,
        report: dict[str, Any],
    ) -> None:
        """Checkpoint, apply commands, then diagnose even after apply failures."""
        checkpoint = artifacts / "checkpoint"
        shutil.copytree(self.project, checkpoint, symlinks=True)
        report["checkpoint"] = str(checkpoint)

        try:
            for command in document["commands"]:
                await self._apply(command, ledger, report)
        except Exception as exc:
            report["errors"].append(
                f"Command application stopped: {str(exc)[:2_000]}"
            )

        await self._diagnose(
            document["check"], ledger, artifacts, report
        )

    async def _apply(
        self,
        command: dict[str, Any],
        ledger: Ledger,
        report: dict[str, Any],
    ) -> None:
        """Apply one workspace operation.

        Delete is intentionally file-only. Image generation is available only
        through an explicitly configured provider.
        """
        target = safe_path(self.project, command["path"])
        operation = command["op"]

        if operation == "write":
            atomic_write(target, command["content"].encode("utf-8"))

        elif operation == "delete":
            if target.is_dir():
                raise ValueError("Recursive directory deletion is unsupported.")
            target.unlink(missing_ok=True)

        elif operation == "generate_image":
            if not self.providers.supports_generation:
                raise NotConfigured(
                    "Image generation provider is not configured."
                )
            allowance = self.policy.generation_reservation_usd
            call_id = ledger.reserve("image_generation", allowance)
            result = await self.providers.generate(
                GenerationRequest(
                    prompt=command["prompt"],
                    width=command["width"],
                    height=command["height"],
                    max_cost_usd=allowance,
                    task_id=self.state.name,
                    iteration=report["iteration"],
                )
            )
            ledger.settle(call_id, result.actual_cost_usd)
            png = self._normalize_image(
                result, command["width"], command["height"]
            )
            atomic_write(target, png)
            report["warnings"].extend(
                str(note)[:1_000] for note in result.notes[:10]
            )

        report["applied_commands"].append(
            {"op": operation, "path": command["path"]}
        )

    @staticmethod
    def _normalize_image(
        result: GeneratedImage, width: int, height: int
    ) -> bytes:
        """Verify exact dimensions and normalize provider output to PNG."""
        if len(result.data) > 30_000_000:
            raise ValueError("Generated image exceeds 30 MB.")
        with Image.open(io.BytesIO(result.data)) as image:
            if image.size != (width, height):
                raise ValueError(
                    f"Expected image size {(width, height)}, got {image.size}."
                )
            image.load()
            output = io.BytesIO()
            image.convert("RGBA").save(output, format="PNG")
            return output.getvalue()

    async def _diagnose(
        self,
        check: dict[str, Any],
        ledger: Ledger,
        artifacts: Path,
        report: dict[str, Any],
    ) -> None:
        """Load the preview, exercise it, capture a screenshot, and review it."""
        screenshot = artifacts / "final.png"

        with preview_server(self.project) as base_url:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch()
                try:
                    context = await browser.new_context(
                        viewport=check.get(
                            "viewport", {"width": 1280, "height": 800}
                        ),
                        device_scale_factor=1,
                        service_workers="block",
                        accept_downloads=False,
                    )
                    page = await context.new_page()
                    page.set_default_timeout(
                        self.policy.action_timeout_ms
                    )
                    page.set_default_navigation_timeout(
                        self.policy.action_timeout_ms
                    )

                    def error(message: str) -> None:
                        """Bound browser diagnostics included in the report."""
                        if len(report["errors"]) < 100:
                            report["errors"].append(message[:2_000])

                    async def restrict_requests(route) -> None:
                        """Permit only resources from this local preview.

                        Data/blob URLs are browser-local. This request policy
                        is not a comprehensive browser security sandbox.
                        """
                        parsed = urlsplit(route.request.url)
                        origin = f"{parsed.scheme}://{parsed.netloc}"
                        if (
                            origin == base_url
                            or parsed.scheme in {"data", "blob"}
                        ):
                            await route.continue_()
                        else:
                            error(
                                "Blocked non-preview request: "
                                + route.request.url
                            )
                            await route.abort()

                    await context.route("**/*", restrict_requests)

                    page.on(
                        "pageerror",
                        lambda exc: error(f"JavaScript exception: {exc}"),
                    )
                    page.on(
                        "console",
                        lambda message: (
                            error(f"Console error: {message.text}")
                            if message.type == "error" else None
                        ),
                    )
                    page.on(
                        "requestfailed",
                        lambda request: error(
                            f"Failed request: {request.url}: "
                            f"{request.failure}"
                        ),
                    )
                    page.on(
                        "response",
                        lambda response: (
                            error(
                                f"HTTP {response.status}: {response.url}"
                            )
                            if response.status >= 400 else None
                        ),
                    )

                    async def dismiss_dialog(dialog) -> None:
                        """Prevent modal dialogs from hanging diagnostics."""
                        error(f"Unexpected dialog: {dialog.message}")
                        await dialog.dismiss()

                    page.on("dialog", dismiss_dialog)

                    from urllib.parse import quote

                    entry = quote(check["page"], safe="/")
                    try:
                        await page.goto(
                            f"{base_url}/{entry}", wait_until="load"
                        )
                        for interaction in check.get("interactions", []):
                            await self._interact(page, interaction)
                            report["interactions"].append(
                                {
                                    "action": interaction["action"],
                                    "status": "passed",
                                }
                            )
                    except Exception as exc:
                        error(f"Browser check failed: {exc}")
                        report["interactions"].append(
                            {"status": "stopped", "reason": str(exc)[:2_000]}
                        )
                    finally:
                        # Capture the viewport after the attempted interactions,
                        # including when an interaction or assertion failed.
                        try:
                            await page.screenshot(
                                path=str(screenshot),
                                full_page=False,
                                animations="disabled",
                                timeout=self.policy.action_timeout_ms,
                            )
                            report["screenshot"] = str(screenshot)
                        except Exception as exc:
                            error(f"Screenshot failed: {exc}")
                finally:
                    await browser.close()

        if not screenshot.exists():
            report["review_status"] = "no_screenshot"
            return

        if not self.providers.supports_review:
            report["review_status"] = "not_configured"
            report["warnings"].append(
                "Screenshot captured, but visual review is not configured."
            )
            return

        report["review_status"] = "running"
        allowance = self.policy.review_reservation_usd
        call_id = ledger.reserve("visual_review", allowance)
        review = await self.providers.review(
            ReviewRequest(
                png=screenshot.read_bytes(),
                expectations=check["visual_expectations"],
                max_cost_usd=allowance,
                task_id=self.state.name,
                iteration=report["iteration"],
            )
        )
        ledger.settle(call_id, review.actual_cost_usd)
        self._validate_review(review)
        report["visual_review"] = {
            "passed": review.passed,
            "findings": [item[:2_000] for item in review.findings[:30]],
            "uncertainties": [
                item[:2_000] for item in review.uncertainties[:30]
            ],
        }
        report["review_status"] = "completed"

    @staticmethod
    def _validate_review(review: VisualReview) -> None:
        """Reject malformed provider judgments rather than guessing intent."""
        if not isinstance(review, VisualReview):
            raise ValueError("Review provider must return VisualReview.")
        if not isinstance(review.passed, bool):
            raise ValueError("VisualReview.passed must be boolean.")
        for values in (review.findings, review.uncertainties):
            if not isinstance(values, list) or not all(
                isinstance(item, str) for item in values
            ):
                raise ValueError("Review findings must be lists of strings.")

    @staticmethod
    async def _interact(page, interaction: dict[str, Any]) -> None:
        """Execute the deliberately small, non-general-purpose action language."""
        from playwright.async_api import expect

        action = interaction["action"]
        if action == "scroll":
            await page.evaluate(
                "p => window.scrollBy(p.x, p.y)",
                {"x": interaction["x"], "y": interaction["y"]},
            )
            return

        locator = page.locator(interaction["selector"])
        if action == "click":
            await locator.click()
        elif action == "fill":
            await locator.fill(interaction["value"])
        elif action == "press":
            await locator.press(interaction["key"])
        elif action == "assert_visible":
            await expect(locator).to_be_visible()
        elif action == "assert_text":
            await expect(locator).to_have_text(interaction["equals"])


def load_providers(specification: str | None) -> Providers:
    """Load a host-selected synchronous factory such as adapters:make_providers.

    This is trusted host configuration, not something the YAML may specify.
    The factory must return a Providers instance.
    """
    if not specification:
        return Providers()
    module_name, separator, factory_name = specification.partition(":")
    if not separator:
        raise ValueError("Provider specification must be module:factory.")
    module = importlib.import_module(module_name)
    provider = getattr(module, factory_name)()
    if not isinstance(provider, Providers):
        raise TypeError("Provider factory must return Providers.")
    return provider


def main() -> None:
    """Run one authoring turn and print a JSON diagnostic report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("document", type=Path)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--providers")
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--max-seconds", type=float, default=900)
    parser.add_argument("--max-usd", type=float, default=2.0)
    parser.add_argument("--review-reserve", type=float, default=0.10)
    parser.add_argument("--image-reserve", type=float, default=0.50)
    args = parser.parse_args()

    workbench = Workbench(
        args.project,
        args.state,
        policy=Policy(
            max_iterations=args.max_iterations,
            max_elapsed_seconds=args.max_seconds,
            max_cost_usd=args.max_usd,
            review_reservation_usd=args.review_reserve,
            generation_reservation_usd=args.image_reserve,
        ),
        providers=load_providers(args.providers),
    )
    report = asyncio.run(
        workbench.run(args.document.read_text(encoding="utf-8"))
    )
    print(json.dumps(report, indent=2, allow_nan=False))
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
