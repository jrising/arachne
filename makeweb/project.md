# Web Authoring Mode: Project Description

## Goal

Create a dedicated mode in which Arachne autonomously builds and refines **static HTML/CSS/JavaScript projects**, then tests their behavior and appearance. No application backend, XML output, or general-purpose JavaScript planning is required within this mode.

Each authoring response is a strict YAML document containing file operations, optional image-generation requests, browser interactions, assertions, and visual expectations. Multiline strings hold source code naturally.

A Python host applies the changes, serves the project locally, runs Playwright diagnostics, captures a final screenshot, and requests visual review. Results feed into another authoring turn until acceptance criteria are met, clarification is needed, or budgets expire.

## Current Starting Point

An initial implementation has been supplied, **but not executed or verified here**. It includes file writes/deletions, checkpoints, static preview, browser interactions, error capture, screenshots, provider interfaces, basic persistent accounting, and tests. Missing visual review correctly produces an incomplete result.

## Remaining Work, in Priority Order

1. **Verify and integrate the MVP.** Run the tests, fix defects, register the mode in the Python host, and define entry, exit, cancellation, and diagnostic-message handling. Keep YAML execution separate from general JavaScript plans.

2. **Close the autonomous feedback loop.** Persist the project brief, acceptance criteria, user feedback, iteration history, and unresolved issues. Supply relevant files and diagnostics to subsequent turns; detect stalled repairs and request clarification when appropriate.

3. **Connect image services.** Implement generation with explicit dimensions and destination paths, screenshot review, and source-image import. Record actual dimensions, resizing/cropping, provenance, available licensing information, and model costs.

4. **Integrate planner accounting.** Use shared reservations and reconciliation for authoring calls, image generation, and image-input reviews. Handle unknown charges, cancellation, overruns, and concurrent operations. Preserve progress and explain why execution stopped.

5. **Strengthen diagnostics.** Add multiple viewports, accessibility checks, richer assertions, reference-image comparisons, and uncertainty-aware visual assessments. Screenshot capture alone must never count as review.

6. **Improve workspace reliability.** Add patches, diffs, checkpoint restoration, safer batch application, crash recovery, artifact retention, and lifecycle cleanup.

7. **Expand safeguards later.** Retain project-root restrictions and isolated browser profiles; full sandboxing is deferred. External research stays outside this mode, with relevant documentation and assets supplied beforehand.

**Success means a reproducible, budget-bounded build–test–review loop—not merely generated files or an attractive screenshot.**
