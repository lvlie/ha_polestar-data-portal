#!/usr/bin/env python3
"""Drive the real API client against a Prism mock of the published spec.

Unit tests mock the transport, so they cannot catch a request that Home
Assistant sends happily but the API would reject. Prism validates every
request against ``resources/openapi.json`` -- required headers, security
scheme, body shape -- so this exercises the actual client against the actual
contract without touching Polestar.

    npx @stoplight/prism-cli mock resources/openapi.json --port 4010 --errors &
    python3 scripts/prism_contract_check.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from custom_components.polestar_data_portal.api import (  # noqa: E402
    PolestarDataPortalApi,
)
from custom_components.polestar_data_portal.const import (  # noqa: E402
    API_DOMAIN_PATHS,
)


async def run(base_url: str) -> int:
    """Call every documented endpoint and report the failures."""
    import aiohttp

    async with aiohttp.ClientSession() as session:
        api = PolestarDataPortalApi(
            session,
            client_id="client_12345",
            client_secret="secret_67890",
            account_id="cf50b789-4e95-4636-977d-4ffb10164d11",
            token_url=f"{base_url}/token",
        )

        try:
            await api.async_get_access_token()
        except Exception as err:
            print(f"FAILED: could not obtain a token: {err}", file=sys.stderr)
            return 1
        print("token endpoint: OK")

        try:
            vins = await api.async_get_vehicles()
        except Exception as err:
            print(f"FAILED: could not list vehicles: {err}", file=sys.stderr)
            return 1

        if not vins:
            print("FAILED: the mock returned no vehicles", file=sys.stderr)
            return 1
        print(f"vehicle list: OK ({len(vins)} vehicle(s))")

        failures: list[str] = []
        for domain in sorted(API_DOMAIN_PATHS):
            try:
                payload = await api.async_get_domain(domain, vins[0])
            except Exception as err:
                failures.append(f"{domain}: {type(err).__name__}: {err}")
                continue
            if not payload:
                failures.append(f"{domain}: empty payload")

        if failures:
            print(
                f"FAILED: {len(failures)} of {len(API_DOMAIN_PATHS)} domains",
                file=sys.stderr,
            )
            for failure in failures:
                print(f"  {failure}", file=sys.stderr)
            return 1

        print(f"all {len(API_DOMAIN_PATHS)} documented domains: OK")
        return 0


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:4010")
    args = parser.parse_args()
    return asyncio.run(run(args.base_url.rstrip("/")))


if __name__ == "__main__":
    raise SystemExit(main())
