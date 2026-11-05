"""Unit and browser smoke tests for the initial authoring workbench.

Run all tests:
    python -m unittest -v

Run tests not requiring a browser:
    python -m unittest -v test_workbench.UnitTests

The example.yaml file is also the browser smoke-test fixture.
No paid model requests are made by this suite.
"""

import tempfile
import unittest
from pathlib import Path

from providers import CallbackProviders, VisualReview
from workbench import (
    BudgetExceeded,
    Ledger,
    Policy,
    Workbench,
    parse_document,
    safe_path,
)


EXAMPLE = Path(__file__).with_name("example.yaml")


class UnitTests(unittest.TestCase):
    """Validate input handling, paths, and persistent budget behavior."""

    def test_example_parses(self):
        """The published example satisfies the authoring schema."""
        document = parse_document(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(document["version"], 1)
        self.assertEqual(len(document["commands"]), 3)

    def test_duplicate_keys_rejected(self):
        """Duplicate keys cannot silently override previous values."""
        with self.assertRaises(ValueError):
            parse_document("version: 1\nversion: 1\n")

    def test_aliases_rejected(self):
        """YAML aliases are outside the supported input language."""
        with self.assertRaises(ValueError):
            parse_document("commands: &items []\ncopy: *items\n")

    def test_unsafe_paths_rejected(self):
        """Paths cannot escape the project or name hidden files."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for relative in (
                "../outside.html",
                "/tmp/outside.html",
                ".env",
                "assets/../../outside.html",
                "assets\\outside.html",
            ):
                with self.subTest(path=relative):
                    with self.assertRaises(ValueError):
                        safe_path(root, relative)

            self.assertEqual(
                safe_path(root, "assets/image.png"),
                root / "assets" / "image.png",
            )

    def test_unknown_cost_retains_reservation(self):
        """Unknown provider charges never become zero-cost operations."""
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            policy = Policy(max_cost_usd=1.0)
            ledger = Ledger(state, policy)
            ledger.begin_iteration()

            call = ledger.reserve("visual_review", 0.25)
            ledger.settle(call, None)

            reloaded = Ledger(state, policy)
            self.assertAlmostEqual(
                reloaded.charged_or_reserved(), 0.25
            )
            self.assertEqual(
                reloaded.summary()["unknown_cost_calls"], 1
            )

    def test_iteration_limit(self):
        """Persisted iteration limits survive ledger reloads."""
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            policy = Policy(max_iterations=1)
            Ledger(state, policy).begin_iteration()

            with self.assertRaises(BudgetExceeded):
                Ledger(state, policy).begin_iteration()

    def test_overrun_is_recorded(self):
        """An excessive provider charge is recorded before stopping."""
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory), Policy())
            ledger.begin_iteration()
            call = ledger.reserve("visual_review", 0.10)

            with self.assertRaises(BudgetExceeded):
                ledger.settle(call, 0.20)

            self.assertAlmostEqual(
                ledger.charged_or_reserved(), 0.20
            )


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    """Exercise real Chromium interactions and screenshot generation."""

    async def test_missing_review_is_incomplete(self):
        """Working behavior cannot substitute for required visual review."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbench = Workbench(
                root / "project",
                root / "state",
            )

            report = await workbench.run(
                EXAMPLE.read_text(encoding="utf-8")
            )

            self.assertEqual(report["errors"], [], report)
            self.assertEqual(report["status"], "incomplete", report)
            self.assertEqual(
                report["review_status"], "not_configured"
            )
            self.assertTrue(Path(report["screenshot"]).exists())
            self.assertTrue(Path(report["checkpoint"]).is_dir())
            self.assertEqual(len(report["interactions"]), 3)

    async def test_review_adapter_and_accounting(self):
        """A synthetic review verifies plumbing, not actual appearance."""
        async def review_stub(request):
            """Test-only provider; never use this as production review."""
            self.assertTrue(request.png.startswith(b"\x89PNG"))
            self.assertIn("counter", request.expectations.lower())
            return VisualReview(
                passed=True,
                findings=["Synthetic test response; no visual assessment."],
                actual_cost_usd=0.02,
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbench = Workbench(
                root / "project",
                root / "state",
                providers=CallbackProviders(review=review_stub),
            )

            report = await workbench.run(
                EXAMPLE.read_text(encoding="utf-8")
            )

            self.assertEqual(report["status"], "passed", report)
            self.assertEqual(report["review_status"], "completed")
            self.assertAlmostEqual(
                report["accounting"]["charged_or_reserved_usd"],
                0.02,
            )

    async def test_javascript_exception_is_reported(self):
        """Runtime failures remain failures even with a screenshot."""
        document = """
version: 1
commands:
  - op: write
    path: index.html
    content: |
      <!doctype html>
      <html lang="en">
        <head>
          <title>Error fixture</title>
          <link rel="icon" href="data:,">
        </head>
        <body>
          <p>Error fixture</p>
          <script>throw new Error("intentional-test-error");</script>
        </body>
      </html>
check:
  page: index.html
  visual_expectations: The error fixture text is visible.
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = await Workbench(
                root / "project", root / "state"
            ).run(document)

            self.assertEqual(
                report["status"], "needs_attention", report
            )
            self.assertTrue(
                any(
                    "intentional-test-error" in error
                    for error in report["errors"]
                ),
                report,
            )
            self.assertTrue(Path(report["screenshot"]).exists())


if __name__ == "__main__":
    unittest.main()
