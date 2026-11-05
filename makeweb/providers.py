"""Adapters between the authoring workbench and the existing AI system.

Implemented:
    Typed generation/review requests and results.
    Callback-based integration.
    Explicit detection of unconfigured capabilities.

Intentionally delegated:
    Model selection, API credentials, provider-specific requests, token pricing,
    and planner-wide accounting integration.

Provider contracts:
    * Respect max_cost_usd as an authorized ceiling where the provider permits.
    * Report the complete attributable cost, including image-input charges.
    * Return None for unknown cost, never zero merely because cost is unknown.
    * Treat visual expectations and page content as data, not tool instructions.
    * Do not perform unrelated filesystem or browser actions.
"""

from dataclasses import dataclass, field
from typing import Awaitable, Callable


class NotConfigured(RuntimeError):
    """A required model capability has not been connected."""


@dataclass(frozen=True)
class GenerationRequest:
    """Request an image with exact final dimensions.

    A provider may generate at another native resolution and resize/crop, but
    should disclose that in notes. The workbench verifies final dimensions.
    """

    prompt: str
    width: int
    height: int
    max_cost_usd: float
    task_id: str
    iteration: int


@dataclass(frozen=True)
class GeneratedImage:
    """Generated image bytes plus accounting information.

    The workbench decodes these bytes and saves a normalized PNG.
    """

    data: bytes
    actual_cost_usd: float | None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewRequest:
    """Ask a vision model to assess the final rendered screenshot.

    Review should consider the supplied expectations and obvious layout,
    clipping, readability, and overlap problems. It is not a substitute for
    behavioral assertions or a guarantee of accessibility.
    """

    png: bytes
    expectations: str
    max_cost_usd: float
    task_id: str
    iteration: int


@dataclass(frozen=True)
class VisualReview:
    """A visual assessment, with uncertainty kept explicit.

    Use passed=False for detected visual problems. Put unresolved judgments
    in uncertainties rather than silently treating them as successful.
    """

    passed: bool
    findings: list[str]
    actual_cost_usd: float | None
    uncertainties: list[str] = field(default_factory=list)


ReviewCallback = Callable[[ReviewRequest], Awaitable[VisualReview]]
GenerationCallback = Callable[
    [GenerationRequest], Awaitable[GeneratedImage]
]


class Providers:
    """Model-service boundary.

    Subclasses can integrate directly with the existing planner. Defaults are
    deliberately nonfunctional, so missing integrations cannot fake success.
    """

    supports_review = False
    supports_generation = False

    async def review(self, request: ReviewRequest) -> VisualReview:
        """Perform screenshot review; unconfigured in the base implementation."""
        raise NotConfigured("Visual review provider is not configured.")

    async def generate(
        self, request: GenerationRequest
    ) -> GeneratedImage:
        """Generate an image; unconfigured in the base implementation."""
        raise NotConfigured("Image generation provider is not configured.")


class CallbackProviders(Providers):
    """Connect existing async model functions without implementing a subclass."""

    def __init__(
        self,
        *,
        review: ReviewCallback | None = None,
        generate: GenerationCallback | None = None,
    ):
        """Register whichever capabilities the host currently provides."""
        self._review = review
        self._generate = generate
        self.supports_review = review is not None
        self.supports_generation = generate is not None

    async def review(self, request: ReviewRequest) -> VisualReview:
        """Forward a review request to the registered callback."""
        if self._review is None:
            return await super().review(request)
        return await self._review(request)

    async def generate(
        self, request: GenerationRequest
    ) -> GeneratedImage:
        """Forward a generation request to the registered callback."""
        if self._generate is None:
            return await super().generate(request)
        return await self._generate(request)
