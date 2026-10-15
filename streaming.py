from __future__ import annotations

import json
from queue import Queue
from threading import Thread
from typing import Any, Callable, Iterable, Mapping

Event = Mapping[str, Any]
ProgressSink = Callable[..., None]
ChunkSource = Iterable[str] | Callable[[ProgressSink], Iterable[str]]


class CompletionEventStream:
    """
    Wrap text chunks as Server-Sent Events.

    Emits:
      event: status
      event: delta
      event: done
      event: error

    `source` can be either:
      - an iterable of text chunks
      - a factory: progress_sink -> iterable of text chunks
    """

    def __init__(
        self,
        source: ChunkSource,
        *,
        done_payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.source = source
        self.done_payload = dict(done_payload or {})
        self._queue: Queue[Event | None] = Queue()
        self.response = ""
        self.streamresponse = None

    def progress_sink(
        self,
        event: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        payload = {**dict(event or {}), **kwargs}
        payload.setdefault("type", "status")
        self._queue.put(payload)

    def emit_delta(self, text: str) -> None:
        self.response += text
        self._queue.put({
            "type": "delta",
            "text": text,
        })

    def close(self) -> None:
        self._queue.put(None)

    def __iter__(self):
        Thread(target=self._run, daemon=True).start()

        while True:
            event = self._queue.get()
            if event is None:
                break
            yield self._format_sse(event)

    def _run(self) -> None:
        try:
            self.progress_sink(
                phase="started",
                message="Thinking…",
            )

            if callable(self.source):
                self.streamresponse = self.source(self.progress_sink)
                iterator = self.streamresponse.chunks
            else:
                iterator = self.source

            for chunk in iterator:
                if chunk:
                    self.emit_delta(chunk)
                    
            self._queue.put({
                "type": "done",
                **self.done_payload,
            })

        except Exception as exc:
            self._queue.put({
                "type": "error",
                "message": f"{type(exc).__name__}: {exc}",
            })
        finally:
            self.close()

    @staticmethod
    def _format_sse(event: Event) -> str:
        return json.dumps(event, ensure_ascii=False, default=str) + "\n"

