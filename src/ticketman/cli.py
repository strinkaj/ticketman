"""CLI entry point — ticketman commands."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from ticketman.config import load_config

app = typer.Typer(
    name="ticketman",
    help="Ticketmaster auto-checkout bot for personal use.",
    no_args_is_help=True,
)

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format=LOG_FORMAT, level=level, stream=sys.stderr)
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)


@app.command()
def login(
    config_path: Annotated[
        Optional[Path], typer.Option("--config", "-c", help="Path to config YAML")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Open browser for manual Ticketmaster login. Session is saved for future runs."""
    _setup_logging(verbose)
    cfg = load_config(config_path)

    async def _login() -> None:
        from ticketman.auth import login_interactive
        from ticketman.browser import BrowserManager

        bm = BrowserManager(cfg.browser)
        try:
            await bm.start()
            success = await login_interactive(bm)
            if success:
                typer.echo("Login successful! Session saved.")
            else:
                typer.echo("Login failed or timed out.", err=True)
                raise typer.Exit(1)
        finally:
            await bm.stop()

    asyncio.run(_login())


@app.command()
def watch(
    url: Annotated[str, typer.Argument(help="Ticketmaster event URL")],
    sections: Annotated[
        Optional[str], typer.Option("--sections", "-s", help="Comma-separated section names")
    ] = None,
    max_price: Annotated[
        Optional[float], typer.Option("--max-price", "-p", help="Maximum ticket price")
    ] = None,
    quantity: Annotated[int, typer.Option("--quantity", "-q", help="Number of tickets")] = 2,
    config_path: Annotated[
        Optional[Path], typer.Option("--config", "-c", help="Path to config YAML")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Add or view a target event for auto-checkout."""
    _setup_logging(verbose)
    cfg = load_config(config_path)

    from ticketman.models import TargetEvent

    target = TargetEvent(
        url=url,
        sections=sections.split(",") if sections else [],
        max_price=max_price,
        quantity=quantity,
    )

    typer.echo(f"Target event configured:")
    typer.echo(f"  URL:      {target.url}")
    typer.echo(f"  Sections: {target.sections or 'Best available'}")
    typer.echo(f"  Max price: ${target.max_price or 'No limit'}")
    typer.echo(f"  Quantity:  {target.quantity}")

    # Add to config targets for this session
    cfg.targets.append(target)
    typer.echo("\nTarget added for this session. Add to config/config.yaml for persistence.")


@app.command()
def run(
    url: Annotated[
        Optional[str], typer.Argument(help="Ticketmaster event URL (or use config targets)")
    ] = None,
    sections: Annotated[
        Optional[str], typer.Option("--sections", "-s", help="Comma-separated section names")
    ] = None,
    max_price: Annotated[
        Optional[float], typer.Option("--max-price", "-p", help="Maximum ticket price")
    ] = None,
    quantity: Annotated[int, typer.Option("--quantity", "-q", help="Number of tickets")] = 2,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Stop before confirming purchase")
    ] = False,
    config_path: Annotated[
        Optional[Path], typer.Option("--config", "-c", help="Path to config YAML")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Monitor event and auto-checkout when tickets are available."""
    _setup_logging(verbose)
    cfg = load_config(config_path)

    # Build target from CLI args or config
    if url:
        from ticketman.models import TargetEvent

        target = TargetEvent(
            url=url,
            sections=sections.split(",") if sections else [],
            max_price=max_price,
            quantity=quantity,
        )
    elif cfg.targets:
        target = cfg.targets[0]
        typer.echo(f"Using first target from config: {target.url}")
    else:
        typer.echo("No target specified. Pass a URL or add targets to config.", err=True)
        raise typer.Exit(1)

    async def _run() -> None:
        from ticketman.auth import check_session
        from ticketman.browser import BrowserManager
        from ticketman.captcha import CaptchaSolver
        from ticketman.checkout import CheckoutFlow
        from ticketman.monitor import EventMonitor
        from ticketman.notify import Notifier

        bm = BrowserManager(cfg.browser)
        solver = CaptchaSolver(cfg.captcha)
        notifier = Notifier(cfg.notifications)

        try:
            await bm.start()

            # Check session
            if not await check_session(bm):
                typer.echo("Session expired. Run 'ticketman login' first.", err=True)
                raise typer.Exit(1)

            typer.echo(f"Session valid. Monitoring: {target.url}")

            # Monitor for tickets
            monitor = EventMonitor(bm, target)
            await monitor.wait_for_onsale()
            await monitor.poll_for_tickets()

            # Tickets found — start checkout
            notifier.notify("Tickets Found!", f"Starting checkout for {target.name or target.url}")

            checkout = CheckoutFlow(bm, solver, cfg, target)

            if dry_run:
                typer.echo("DRY RUN — stopping before purchase confirmation.")
                await bm.screenshot("dry_run_checkout")
                notifier.notify("Dry Run Complete", "Checkout flow reached — stopped before payment")
                return

            # Retry loop for checkout
            max_retries = 3
            for attempt in range(1, max_retries + 1):
                typer.echo(f"Checkout attempt {attempt}/{max_retries}...")
                try:
                    success = await checkout.run()
                    if success:
                        notifier.notify(
                            "Purchase Complete!",
                            f"Got {target.quantity} tickets for {target.name or target.url}",
                        )
                        return
                except Exception as e:
                    typer.echo(f"Attempt {attempt} failed: {e}", err=True)
                    if attempt < max_retries:
                        typer.echo("Retrying...")
                        await asyncio.sleep(2)

            notifier.notify("Purchase Failed", f"All {max_retries} attempts failed")
            typer.echo("All checkout attempts failed.", err=True)
            raise typer.Exit(1)

        finally:
            await solver.close()
            await bm.stop()

    asyncio.run(_run())


@app.command()
def status(
    config_path: Annotated[
        Optional[Path], typer.Option("--config", "-c", help="Path to config YAML")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Show current configuration and session status."""
    _setup_logging(verbose)
    cfg = load_config(config_path)

    typer.echo("Ticketman Status")
    typer.echo("=" * 40)
    typer.echo(f"Email:    {cfg.ticketmaster.email or 'Not configured'}")
    typer.echo(f"CAPTCHA:  {cfg.captcha.provider} (key {'set' if cfg.captcha.api_key else 'NOT set'})")
    typer.echo(f"Payment:  card ending {cfg.payment.card_last4 or 'NOT set'}")
    typer.echo(f"Notify:   desktop={'on' if cfg.notifications.desktop else 'off'}, sms={'on' if cfg.notifications.sms else 'off'}")
    typer.echo(f"Browser:  headless={cfg.browser.headless}, profile={cfg.browser.profile_dir}")

    if cfg.targets:
        typer.echo(f"\nTargets ({len(cfg.targets)}):")
        for i, t in enumerate(cfg.targets, 1):
            typer.echo(f"  {i}. {t.name or t.url}")
            typer.echo(f"     Sections: {t.sections or 'Best available'}")
            typer.echo(f"     Max: ${t.max_price or 'No limit'} × {t.quantity}")
            if t.on_sale:
                typer.echo(f"     On-sale: {t.on_sale.isoformat()}")
    else:
        typer.echo("\nNo targets configured.")


if __name__ == "__main__":
    app()
