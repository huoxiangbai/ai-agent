"""Generate a runnable drill nginx.conf from the production ``docker/nginx.conf``.

The production file is a server+upstream fragment meant for ``/etc/nginx/conf.d/``
inside the image's ``http`` block, so it cannot be loaded standalone. This
generator wraps it in the minimal ``events``/``http`` scaffolding and performs
exactly four environment substitutions — upstream hostnames, the listen port, the
document root, and the featured-fragment include path. Everything else is copied
through verbatim, so ``nginx -t`` on the output is a real syntax check of the
production routing config (including ``include .../*.conf`` and the three
location blocks), not of a hand-written lookalike.

Each substitution asserts that its pattern matched exactly once. If
``docker/nginx.conf`` drifts (a renamed upstream, a moved include) the generator
fails loudly instead of producing a config that silently tests nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WRAPPER_HEAD = """\
worker_processes 1;
pid {prefix}/nginx.pid;
error_log {prefix}/error.log warn;
events {{ worker_connections 128; }}
http {{
    default_type application/octet-stream;
    sendfile off;
    client_body_temp_path {prefix}/tmp/client_body;
    proxy_temp_path {prefix}/tmp/proxy;
    fastcgi_temp_path {prefix}/tmp/fastcgi;
    uwsgi_temp_path {prefix}/tmp/uwsgi;
    scgi_temp_path {prefix}/tmp/scgi;
    log_format cutover '$remote_addr [$time_local] "$request" '
                       '$status $body_bytes_sent upstream="$upstream_addr" '
                       'rt=$request_time';
    access_log {prefix}/access.log cutover;
"""

WRAPPER_TAIL = """\
}
"""

# (label, old, new) — each `old` must occur exactly once in the production file.
# `new` is a ``str.format`` template over ``prefix``/``listen_port``/``java_port``/
# ``python_port``/``tool_port``. The upstream *ports* are parameters so the drill
# can bind Java/Python to free ports when :8100/:8200 are held by another process
# (the defaults reproduce the phase-3B drill exactly).
SUBSTITUTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "java upstream hostname",
        "server reactor-backend:8100;",
        "server 127.0.0.1:{java_port};",
    ),
    (
        "python upstream hostname",
        "server reactor-backend-python:8200;",
        "server 127.0.0.1:{python_port};",
    ),
    (
        "tool upstream hostname",
        "server reactor-tool:1601;",
        "server 127.0.0.1:{tool_port};",
    ),
    (
        "listen port",
        "listen 80;",
        "listen 127.0.0.1:{listen_port};",
    ),
    (
        "document root",
        "root /usr/share/nginx/html;",
        "root {prefix}/html;",
    ),
    (
        "featured-fragment include path",
        "include /etc/nginx/featured-python.d/*.conf;",
        "include {prefix}/featured-python.d/*.conf;",
    ),
)


def generate(
    source: Path,
    prefix: Path,
    listen_port: int,
    *,
    java_port: int = 8100,
    python_port: int = 8200,
    tool_port: int = 1601,
) -> str:
    body = source.read_text(encoding="utf-8")
    replacements = {
        "prefix": str(prefix),
        "listen_port": listen_port,
        "java_port": java_port,
        "python_port": python_port,
        "tool_port": tool_port,
    }
    for label, old, new in SUBSTITUTIONS:
        count = body.count(old)
        if count != 1:
            raise SystemExit(
                f"drill config generation failed: expected exactly one {label!r} "
                f"({old!r}) in {source}, found {count}. The production nginx.conf "
                "drifted — update SUBSTITUTIONS before running the drill."
            )
        body = body.replace(old, new.format(**replacements))
    return (
        WRAPPER_HEAD.format(prefix=str(prefix))
        + body
        + WRAPPER_TAIL
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--listen-port", type=int, default=18080)
    parser.add_argument(
        "--java-upstream-port",
        type=int,
        default=8100,
        help="port of the Java backend (default 8100; override when :8100 is held)",
    )
    parser.add_argument(
        "--python-upstream-port",
        type=int,
        default=8200,
        help="port of the Python backend (default 8200; override when :8200 is held)",
    )
    parser.add_argument("--tool-upstream-port", type=int, default=1601)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    text = generate(
        args.source,
        args.prefix,
        args.listen_port,
        java_port=args.java_upstream_port,
        python_port=args.python_upstream_port,
        tool_port=args.tool_upstream_port,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {args.output} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
