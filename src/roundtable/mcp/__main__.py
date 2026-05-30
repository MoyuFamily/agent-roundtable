# type: ignore
"""Entry point: python -m roundtable.mcp"""

import argparse
import asyncio


def main() -> None:
    parser = argparse.ArgumentParser(description="Roundtable MCP Server")
    parser.add_argument("--http", action="store_true", help="Run as HTTP/SSE server instead of stdio")
    parser.add_argument("--port", type=int, default=8200, help="HTTP port (default: 8200)")
    parser.add_argument("--db", type=str, default=None, help="SQLite database path")
    args = parser.parse_args()

    from roundtable.mcp.server import create_server

    server = create_server(db_path=args.db)

    if args.http:
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
                await server.run(streams[0], streams[1], server.create_initialization_options())

        app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ]
        )

        import uvicorn

        uvicorn.run(app, host="0.0.0.0", port=args.port)
    else:
        from mcp.server.stdio import stdio_server

        async def run_stdio():
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())

        asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
