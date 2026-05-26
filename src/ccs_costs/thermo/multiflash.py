"""Optional Multiflash MCP integration for rigorous CO2 EOS.

Provides an accuracy upgrade path using the existing Multiflash MCP server
(Span-Wagner EOS) when available, with automatic fallback to the built-in
Duan EOS when the server is not reachable.

The engine ALWAYS works without Multiflash. Multiflash is an accuracy
upgrade, not a dependency. Any failure in Multiflash communication results
in a silent fallback to the built-in Duan EOS.

Functions:
    multiflash_available: Check if Multiflash MCP server is reachable
    multiflash_co2_density: Call Multiflash for rigorous Span-Wagner density
    get_co2_density: Unified entry point with optional Multiflash upgrade
"""

from __future__ import annotations

import asyncio
import logging

from ccs_costs.thermo.co2 import co2_density

logger = logging.getLogger(__name__)


async def multiflash_available(timeout: float = 2.0) -> bool:
    """Check if Multiflash MCP server is reachable.

    Attempts a lightweight connection to the Multiflash MCP server.
    Returns False on any error (connection refused, timeout, import error).

    Args:
        timeout: Connection timeout in seconds. Default 2.0.

    Returns:
        True if the server responds, False otherwise.
    """
    try:
        import httpx  # noqa: F811
    except ImportError:
        logger.debug("httpx not installed; Multiflash MCP unavailable")
        return False

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Try to reach the Multiflash MCP server health endpoint
            # The actual endpoint depends on the MCP server implementation
            response = await client.get("http://localhost:8080/health")
            return response.status_code == 200
    except Exception:
        return False


async def multiflash_co2_density(
    pressure_mpa: float, temperature_c: float
) -> float:
    """Call Multiflash MCP for rigorous Span-Wagner CO2 density.

    Args:
        pressure_mpa: Pressure in MPa.
        temperature_c: Temperature in Celsius.

    Returns:
        CO2 density in kg/m3 from Span-Wagner EOS.

    Raises:
        RuntimeError: If Multiflash server is not available or returns error.
    """
    try:
        import httpx  # noqa: F811
    except ImportError:
        raise RuntimeError("httpx not installed; cannot call Multiflash MCP")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Call the pt_flash tool via MCP protocol
            response = await client.post(
                "http://localhost:8080/tools/pt_flash",
                json={
                    "pressure_mpa": pressure_mpa,
                    "temperature_c": temperature_c,
                    "composition": {"CO2": 1.0},
                },
            )
            response.raise_for_status()
            data = response.json()
            return float(data["density_kgm3"])
    except Exception as exc:
        raise RuntimeError(
            f"Multiflash MCP call failed: {exc}"
        ) from exc


def get_co2_density(
    pressure_mpa: float,
    temperature_c: float,
    prefer_multiflash: bool = False,
) -> float:
    """Get CO2 density with optional Multiflash upgrade.

    The engine ALWAYS works without Multiflash. Multiflash is an
    accuracy upgrade, not a dependency. If prefer_multiflash is True
    and the server is available, uses Span-Wagner EOS. Otherwise
    falls back to built-in Duan (1992) EOS.

    Args:
        pressure_mpa: Pressure in MPa.
        temperature_c: Temperature in Celsius.
        prefer_multiflash: If True, try Multiflash first. Default False.

    Returns:
        CO2 density in kg/m3.
    """
    if prefer_multiflash:
        try:
            # Check if we're already in an async context
            try:
                loop = asyncio.get_running_loop()
                # Already in async context -- can't use asyncio.run()
                # Fall back to built-in EOS
                logger.debug(
                    "Already in async context; using Duan EOS fallback"
                )
                return co2_density(pressure_mpa, temperature_c, method="duan")
            except RuntimeError:
                pass  # No running loop -- we can use asyncio.run()

            if asyncio.run(multiflash_available()):
                density = asyncio.run(
                    multiflash_co2_density(pressure_mpa, temperature_c)
                )
                logger.info(
                    "Using Multiflash Span-Wagner density: %.2f kg/m3",
                    density,
                )
                return density
        except Exception:
            # Any failure -> fall back to built-in EOS
            logger.debug("Multiflash unavailable; using Duan EOS fallback")

    return co2_density(pressure_mpa, temperature_c, method="duan")
