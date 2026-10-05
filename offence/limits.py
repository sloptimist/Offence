"""ASGI limits cover the entire response, including slow streaming consumers."""
import asyncio
from starlette.responses import JSONResponse


class ResourceLimits:
    def __init__(self, app, max_active=32, send_timeout=10, lifetime=3660):
        self.app, self.max_active = app, max_active
        self.send_timeout, self.lifetime, self.active = send_timeout, lifetime, 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if self.active >= self.max_active:
            return await JSONResponse({"detail": "Server busy"}, 503)(scope, receive, send)
        self.active += 1
        started = False

        async def bounded_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            async with asyncio.timeout(self.send_timeout):
                await send(message)
        try:
            async with asyncio.timeout(self.lifetime):
                await self.app(scope, receive, bounded_send)
        except TimeoutError:
            if not started:
                await JSONResponse({"detail": "Request deadline exceeded"}, 408)(scope, receive, bounded_send)
            # After response headers, close the stream without a success marker.
        finally:
            self.active -= 1
