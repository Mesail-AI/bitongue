from collections.abc import AsyncGenerator, Collection
from typing import TYPE_CHECKING

import anyio
from aioresult import ResultCapture

from bitongue.flow import BaseMessage, Flowing
from bitongue.handler import BaseResult, MessageHandleFailure

from .exceptions import MessageHandleError

if TYPE_CHECKING:
    from bitongue.filter import BaseFilter
    from bitongue.handler import BaseHandler

    from .config import BitongueConfig


class Bitongue[T: BaseMessage, R: BaseResult]:
    """Client that owns the full message flowing lifecycle.

    It wires a handler and an optional filter chain together with a
    :class:`bitongue.flow.Flowing` window created from the config:
    :meth:`start` opens the window, :meth:`send` feeds it, and
    :meth:`result` drains it through expiry removal, the filter chain, and
    the handler. Call :meth:`shutdown` when done. Filters implementing
    :class:`bitongue.filter.FilterLifecycle` are started and closed with
    the client.
    """

    def __init__(
        self,
        config: "BitongueConfig",
        *,
        handler: "BaseHandler[T, R]",
        filters: Collection["BaseFilter[T]"] | None = None,
    ) -> None:

        self._config = config
        self._handler = handler
        self._filters = filters or []

        self._flow: Flowing[T] | None = None

        self._running = False

    @property
    def running(self) -> bool:

        return self._running

    async def start(self) -> None:
        """Create the flowing window from the config and start it.

        Filters implementing :class:`bitongue.filter.FilterLifecycle`
        are started afterwards — detected structurally, to keep this
        module import-light — so their initialization cost lands on
        client start-up instead of the first filtered message. Filter
        ``start`` should be idempotent, matching this method's own
        contract: calling it on a started client does nothing.
        """

        if self._running:
            return

        if self._flow is None:
            self._flow = Flowing[T](
                size=self._config.flowing_size,
                timeout=self._config.flowing_timeout,
            )

        if not self._flow.running:
            await self._flow.start()

        for lifecycle_filter in self._filters:
            start = getattr(lifecycle_filter, "start", None)

            if start is not None:
                await start()

        self._running = True

    async def shutdown(self) -> None:
        """Stop the flowing window and release it.

        Filters implementing :class:`bitongue.filter.FilterLifecycle`
        are closed first, in reverse start order. Messages still
        buffered in the window are discarded.

        Idempotent: calling it on a stopped client does nothing.
        """

        if not self._running:
            return

        for lifecycle_filter in reversed(list(self._filters)):
            aclose = getattr(lifecycle_filter, "aclose", None)

            if aclose is not None:
                await aclose()

        if self._flow is not None:
            if self._flow.running:
                await self._flow.shutdown()

            self._flow = None

        self._running = False

    async def send(self, message: "T") -> None:
        """Put a message into the flowing window.

        Waits while the window is full until the consumer makes room.

        Raises:
            RuntimeError: If the client has not been started, or was
                shut down after starting.
        """

        if not self._running or self._flow is None or not self._flow.running:
            raise RuntimeError("Run `start` first.")

        await self._flow.draw(message)

    async def _filtered(self, message: "T") -> bool:

        captures: list[ResultCapture[bool]] = []
        async with anyio.create_task_group() as tg:
            captures.extend(
                ResultCapture.start_soon(
                    tg,
                    _filter.filter,
                    message,
                    suppress_exception=True,
                )
                for _filter in self._filters
            )

        # Wait for every filter, then fail loudly: sibling failures are
        # peers, not a cause chain, so all of them go into one group.
        failures: list[BaseException] = []
        for capture in captures:
            failure = capture.exception()

            if failure is not None:
                failures.append(failure)

        if failures:
            raise BaseExceptionGroup("Filter chain failed.", failures)

        return not all(capture.result() for capture in captures)

    async def _handle(self, message: "T") -> "R | None":

        with anyio.fail_after(self._config.handle_timeout):
            if await self._filtered(message):
                return None

            try:
                return await self._handler.handle(message)

            except Exception as exc:
                raise MessageHandleError(
                    f"Message handle failed. Error: {exc}",
                ) from exc

    async def result(self) -> AsyncGenerator["R | MessageHandleFailure[T]", None]:
        """Yield handling results for messages drawn from the window.

        Each message passes, in order: expiry removal, the filter chain —
        filters run concurrently and every one must accept; the chain
        does not short-circuit — and the handler. The configured handle
        timeout bounds filtering and handling together. Failures are
        treated by the scope of the fault:

        - A message past its lifetime or rejected by a filter is skipped
          silently — no result, later messages unaffected.
        - A handling timeout also skips the message silently: nothing
          informative happened to report.
        - An exception raised inside the handler is a message-scoped
          failure: it is wrapped into :class:`MessageHandleError` and
          emitted as a :class:`bitongue.handler.MessageHandleFailure`
          envelope, in order, and the stream keeps consuming later
          messages.
        - An exception raised by a filter is a pipeline-scoped failure:
          every filter in the chain is awaited, all their exceptions are
          collected into one :class:`ExceptionGroup` and raised, which
          terminates the stream — a broken admission mechanism cannot
          decide any further message.

        Normal results are handler-defined ``R`` structures; the failure
        envelope is the library's own
        :class:`bitongue.handler.MessageHandleFailure`, so consumers tell
        the two apart with ``isinstance``.

        The underlying stream is single-consumer: only one task may
        iterate this generator at a time.

        Raises:
            RuntimeError: If the client has not been started, or was
                shut down after starting.
        """

        if self._flow is None or not self._flow.running:
            raise RuntimeError("Run `start` first.")

        async for message in self._flow.flow():
            try:
                result = await self._handle(message)

                if result is not None:
                    yield result

            except anyio.get_cancelled_exc_class():
                raise

            except MessageHandleError as err:
                yield MessageHandleFailure[T](message=message, error=str(err))

            except TimeoutError:
                continue
