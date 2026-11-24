"""In-process result collection for multi-file command dispatch.

Single-file commands keep their normal error and transaction handling. The
collector receives their structured envelopes before serialization, never
parses stdout, and is reset before the aggregate is emitted.
"""

from contextvars import ContextVar

RESULT_COLLECTOR: ContextVar[list[dict] | None] = ContextVar("result_collector", default=None)
