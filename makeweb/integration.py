"""Illustrative host integration; supply your existing model callbacks."""

from pathlib import Path

from providers import CallbackProviders
from workbench import Workbench


def create_authoring_mode(review_callback, generation_callback):
    """Construct the mode using host-owned, metered model adapters.

    Callbacks receive ReviewRequest or GenerationRequest and must return
    VisualReview or GeneratedImage respectively.
    """
    return Workbench(
        project=Path("./demo-project"),
        state=Path("./demo-state"),
        providers=CallbackProviders(
            review=review_callback,
            generate=generation_callback,
        ),
    )


async def process_authoring_response(mode, yaml_response):
    """Apply one model response and return diagnostics for the next turn."""
    return await mode.run(yaml_response)
