"""CLI entry point for ticketman.

Commands:
  find        search Ticketmaster events by keyword
  info        show one event's schedule and price range
  plan        score sellout risk and build a presale + group plan
  watch       poll an event and desktop-alert on sale windows and price drops
  checklist   print a prep checklist per person in your group
  watchlist   manage the portfolio of events under coordination
  register    record that a person registered for an event's lottery/presale
  result      record a person's lottery outcome and purchase window
  purchased   record a completed purchase
  board       war-room view of registrations, wins, and assignments
  calendar    export deadlines and windows to an .ics file
  outcome     label a past event (sold out or not) for calibration
  calibrate   check how well the sellout score matches your labeled outcomes
  roster      manage your buying group (add / list / remove)
  status      show config and roster summary

None of these buy tickets. They tell you when and how to be ready so you and
your friends can each check out, by hand, on your own accounts.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from ticketman.config import (
    load_config,
    load_outcomes,
    load_registrations,
    load_roster,
    load_watchlist,
    save_outcomes,
    save_registrations,
    save_roster,
    save_watchlist,
)
from ticketman.models import Participant

app = typer.Typer(
    name="ticketman",
    help="Alerting and coordination to land retail concert tickets for your group.",
    no_args_is_help=True,
)
roster_app = typer.Typer(name="roster", help="Manage your buying group.", no_args_is_help=True)
app.add_typer(roster_app)
watchlist_app = typer.Typer(
    name="watchlist", help="Manage the portfolio of tracked events.", no_args_is_help=True
)
app.add_typer(watchlist_app)
outcome_app = typer.Typer(
    name="outcome", help="Label past events for calibration.", no_args_is_help=True
)
app.add_typer(outcome_app)

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format=LOG_FORMAT, level=level, stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _fmt_dt(dt: datetime | None, tz=None) -> str:
    """Format a UTC datetime in a target timezone, or local time if tz is None."""
    if dt is None:
        return "TBA"
    local = dt.astimezone(tz)
    return local.strftime("%a %b %d, %Y %I:%M %p %Z")


def _parse_when(value: str | None) -> datetime | None:
    """Parse an ISO datetime CLI argument. Naive input is treated as local."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            f"Could not parse '{value}'. Use ISO format, e.g. 2026-05-01T14:00."
        ) from exc
    if dt.tzinfo is None:
        dt = dt.astimezone()  # attach local timezone
    return dt


def _client(cfg):
    from ticketman.discovery import DiscoveryClient

    return DiscoveryClient(cfg.ticketmaster.api_key, cfg.ticketmaster.country_code)


ConfigOpt = Annotated[Path | None, typer.Option("--config", "-c", help="Path to config YAML")]
VerboseOpt = Annotated[bool, typer.Option("--verbose", "-v")]


@app.command()
def find(
    keyword: Annotated[str, typer.Argument(help="Artist, team, or event keyword")],
    city: Annotated[str | None, typer.Option("--city", help="Limit to a city")] = None,
    size: Annotated[int, typer.Option("--size", help="Max results")] = 15,
    config_path: ConfigOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Search events and print their ids, dates, and on-sale times."""
    _setup_logging(verbose)
    cfg = load_config(config_path)
    with _client(cfg) as client:
        events = client.search_events(keyword, city=city, size=size)

    if not events:
        typer.echo("No events found.")
        raise typer.Exit(0)

    for e in events:
        onsale = e.public_sale.start if e.public_sale else None
        typer.echo(f"\n{e.name}")
        typer.echo(f"  id:       {e.id}")
        typer.echo(f"  when:     {e.start_local or 'TBA'}  ({e.venue_name}, {e.city} {e.state})")
        typer.echo(f"  status:   {e.status or 'unknown'}")
        typer.echo(f"  on-sale:  {_fmt_dt(onsale)}")
        if e.presales:
            typer.echo(f"  presales: {len(e.presales)}")


@app.command()
def info(
    event: Annotated[str, typer.Argument(help="Event URL or id")],
    config_path: ConfigOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Show one event's full sale schedule and price range."""
    _setup_logging(verbose)
    cfg = load_config(config_path)
    with _client(cfg) as client:
        e = client.get_event(event)

    typer.echo(f"\n{e.name}")
    typer.echo(f"  {e.venue_name}, {e.city} {e.state}")
    typer.echo(f"  event date: {e.start_local or 'TBA'}")
    typer.echo(f"  status:     {e.status or 'unknown'}")
    if e.price_min is not None or e.price_max is not None:
        lo = f"${e.price_min:.0f}" if e.price_min is not None else "?"
        hi = f"${e.price_max:.0f}" if e.price_max is not None else "?"
        typer.echo(f"  price:      {lo} to {hi} {e.currency}")

    typer.echo("\n  Sale windows:")
    for ps in e.presales:
        typer.echo(f"    presale: {ps.name}")
        typer.echo(f"             {_fmt_dt(ps.start)}  to  {_fmt_dt(ps.end)}")
    if e.public_sale:
        typer.echo("    public on-sale:")
        typer.echo(f"             {_fmt_dt(e.public_sale.start)}  to  {_fmt_dt(e.public_sale.end)}")
    if not e.presales and not e.public_sale:
        typer.echo("    none announced yet. Use 'watch' to catch them.")


@app.command()
def plan(
    event: Annotated[str, typer.Argument(help="Event URL or id")],
    quantity: Annotated[int, typer.Option("--quantity", "-q", help="Tickets you want total")] = 4,
    config_path: ConfigOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Score sellout risk and build a presale plus group plan."""
    _setup_logging(verbose)
    cfg = load_config(config_path)
    roster = load_roster()
    with _client(cfg) as client:
        e = client.get_event(event)

    from ticketman.strategy import build_plan

    ep = build_plan(e, roster, cfg.strategy, target_qty=quantity)

    typer.echo(f"\n{e.name}  ({e.venue_name}, {e.city} {e.state})")
    typer.echo(f"event date: {e.start_local or 'TBA'}\n")

    typer.echo(f"SELLOUT RISK: {ep.sellout.score:.0f}/100  ({ep.sellout.tier})")
    typer.echo("  factor                     value  weight  contribution  note")
    for f in ep.sellout.factors:
        typer.echo(
            f"  {f.name:<24} {f.normalized:>5.2f}  {f.weight:>5.2f}  "
            f"{f.contribution:>11.3f}  {f.note}"
        )

    typer.echo("\nSALE WINDOWS (soonest first):")
    for w in ep.windows:
        flags = []
        if w.needs_registration:
            flags.append("register ahead")
        if w.needs_code:
            flags.append("needs code/cardholder")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        typer.echo(f"  {w.kind:<8} {w.name}{flag_str}")
        typer.echo(f"           opens {_fmt_dt(w.start)}")
        if w.eligible:
            typer.echo(f"           in-group access: {', '.join(w.eligible)}")

    if ep.group:
        typer.echo("\nGROUP PLAN:")
        typer.echo(f"  primary buyer: {ep.group.primary_buyer}")
        if ep.group.backups:
            typer.echo(f"  backups:       {', '.join(ep.group.backups)}")
        typer.echo(f"  buy up to {ep.group.per_person_quantity} on the account that clears first")
        typer.echo(f"  {ep.group.rationale}")
    else:
        typer.echo("\nGROUP PLAN: no roster yet. Add people with 'ticketman roster add'.")

    typer.echo(f"\nRECOMMENDATION:\n  {ep.recommendation}")


@app.command()
def watch(
    event: Annotated[str, typer.Argument(help="Event URL or id")],
    interval: Annotated[
        float, typer.Option("--interval", "-i", help="Seconds between polls")
    ] = 60.0,
    config_path: ConfigOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Poll an event and desktop-alert on sale windows and price drops."""
    _setup_logging(verbose)
    cfg = load_config(config_path)

    from ticketman.notify import Notifier
    from ticketman.watch import watch_event

    if interval < 30:
        typer.echo("Interval below 30s risks rate limiting. Clamping to 30s.", err=True)
        interval = 30.0

    notifier = Notifier(cfg.notifications)
    typer.echo(f"Watching {event}. Press Ctrl-C to stop.")
    with _client(cfg) as client:
        try:
            watch_event(client, notifier, event, interval=interval)
        except KeyboardInterrupt:
            typer.echo("\nStopped.")


@app.command()
def checklist(
    event: Annotated[str, typer.Argument(help="Event URL or id")],
    config_path: ConfigOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Print a prep checklist for each person in your group."""
    _setup_logging(verbose)
    cfg = load_config(config_path)
    roster = load_roster()
    with _client(cfg) as client:
        e = client.get_event(event)

    from ticketman.strategy import build_plan

    ep = build_plan(e, roster, cfg.strategy)
    reg_windows = [w for w in ep.windows if w.needs_registration]

    typer.echo(f"\nPREP CHECKLIST: {e.name}\n")
    typer.echo("Everyone, before on-sale day:")
    typer.echo("  [ ] Logged into ticketmaster.com and session is active")
    typer.echo("  [ ] A payment method is saved on the account")
    typer.echo("  [ ] Delivery address / phone confirmed")
    if reg_windows:
        for w in reg_windows:
            typer.echo(f"  [ ] Registered for Verified Fan: {w.name} (before it closes)")
    typer.echo("  [ ] Know the exact window time in your timezone (see 'ticketman info')")

    if not roster.participants:
        typer.echo("\nNo roster yet. Add people with 'ticketman roster add' for per-person prep.")
        return

    typer.echo("\nPer person:")
    for p in roster.participants:
        typer.echo(f"\n  {p.name} ({p.account_email or 'no email set'})")
        access = ", ".join(p.access) if p.access else "none recorded"
        typer.echo(f"    access tags: {access}")
        for w in ep.windows:
            if w.name in ["General public on-sale"]:
                continue
            can = p.name in w.eligible
            mark = "x" if can else " "
            typer.echo(f"    [{mark}] eligible for '{w.name}'")


@roster_app.command("add")
def roster_add(
    name: Annotated[str, typer.Argument(help="Person's name")],
    email: Annotated[str, typer.Option("--email", help="Account email")] = "",
    city: Annotated[str, typer.Option("--city", help="Their city")] = "",
    timezone: Annotated[
        str, typer.Option("--timezone", help="IANA tz, e.g. America/New_York")
    ] = "",
    access: Annotated[
        str | None,
        typer.Option("--access", help="Comma-separated tags: amex,citi,fan-club,verified-fan"),
    ] = None,
    notes: Annotated[str, typer.Option("--notes", help="Free-form notes")] = "",
) -> None:
    """Add or update a person in the buying group."""
    _setup_logging(False)
    roster = load_roster()
    tags = [t.strip() for t in access.split(",")] if access else []

    existing = roster.find(name)
    if existing:
        existing.account_email = email or existing.account_email
        existing.city = city or existing.city
        existing.timezone = timezone or existing.timezone
        if tags:
            existing.access = tags
        existing.notes = notes or existing.notes
        typer.echo(f"Updated {name}.")
    else:
        roster.participants.append(
            Participant(
                name=name,
                account_email=email,
                city=city,
                timezone=timezone,
                access=tags,
                notes=notes,
            )
        )
        typer.echo(f"Added {name}.")

    path = save_roster(roster)
    typer.echo(f"Roster saved to {path}.")
    if roster.duplicate_emails():
        typer.echo(
            "WARNING: an email is now shared by more than one person. Each account "
            "must belong to a distinct real person.",
            err=True,
        )


@roster_app.command("list")
def roster_list() -> None:
    """List everyone in the buying group."""
    roster = load_roster()
    if not roster.participants:
        typer.echo("Roster is empty. Add people with 'ticketman roster add'.")
        return
    typer.echo(f"Buying group ({len(roster.participants)}):")
    for p in roster.participants:
        access = ", ".join(p.access) if p.access else "no access tags"
        typer.echo(f"  {p.name:<20} {p.account_email or '(no email)':<28} {access}")
        if p.notes:
            typer.echo(f"    note: {p.notes}")


@roster_app.command("remove")
def roster_remove(
    name: Annotated[str, typer.Argument(help="Person to remove")],
) -> None:
    """Remove a person from the buying group."""
    roster = load_roster()
    before = len(roster.participants)
    roster.participants = [p for p in roster.participants if p.name.lower() != name.lower()]
    if len(roster.participants) == before:
        typer.echo(f"No one named {name} in the roster.")
        raise typer.Exit(1)
    save_roster(roster)
    typer.echo(f"Removed {name}.")


@app.command()
def status(config_path: ConfigOpt = None, verbose: VerboseOpt = False) -> None:
    """Show config and roster summary."""
    _setup_logging(verbose)
    cfg = load_config(config_path)
    roster = load_roster()

    typer.echo("Ticketman status")
    typer.echo("=" * 40)
    key_set = (
        "set" if cfg.ticketmaster.api_key else "NOT set (get one at developer.ticketmaster.com)"
    )
    typer.echo(f"Discovery API key: {key_set}")
    typer.echo(f"Country:           {cfg.ticketmaster.country_code}")
    typer.echo(f"Desktop alerts:    {'on' if cfg.notifications.desktop else 'off'}")
    typer.echo(f"Buying group:      {len(roster.participants)} people")
    for p in roster.participants:
        typer.echo(f"  - {p.name} ({p.account_email or 'no email'})")


# ---------------------------------------------------------------------------
# Portfolio (watchlist)
# ---------------------------------------------------------------------------


@watchlist_app.command("add")
def watchlist_add(
    event: Annotated[str, typer.Argument(help="Event URL or id")],
    quantity: Annotated[int, typer.Option("--quantity", "-q", help="Tickets you want")] = 4,
    notes: Annotated[str, typer.Option("--notes", help="Free-form notes")] = "",
    config_path: ConfigOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Fetch an event and add it to the portfolio."""
    _setup_logging(verbose)
    cfg = load_config(config_path)
    with _client(cfg) as client:
        e = client.get_event(event)

    from datetime import date

    from ticketman.models import WatchlistEntry

    wl = load_watchlist()
    entry = wl.find(e.id)
    if entry:
        entry.target_qty = quantity
        entry.notes = notes or entry.notes
        typer.echo(f"Updated watchlist entry for {e.name}.")
    else:
        wl.events.append(
            WatchlistEntry(
                event_id=e.id,
                name=e.name,
                url=e.url,
                event_date=e.start_local,
                city=e.city,
                target_qty=quantity,
                added_at=date.today().isoformat(),
                notes=notes,
            )
        )
        typer.echo(f"Added {e.name} to the watchlist.")
    save_watchlist(wl)


@watchlist_app.command("remove")
def watchlist_remove(
    event_id: Annotated[str, typer.Argument(help="Event id to remove")],
) -> None:
    """Remove an event from the portfolio."""
    wl = load_watchlist()
    before = len(wl.events)
    wl.events = [e for e in wl.events if e.event_id != event_id]
    if len(wl.events) == before:
        typer.echo(f"No watchlist entry with id {event_id}.")
        raise typer.Exit(1)
    save_watchlist(wl)
    typer.echo(f"Removed {event_id}.")


@watchlist_app.command("list")
def watchlist_list() -> None:
    """List the portfolio with per-event registration counts."""
    wl = load_watchlist()
    reg_log = load_registrations()
    if not wl.events:
        typer.echo("Watchlist is empty. Add events with 'ticketman watchlist add'.")
        return

    from ticketman.board import build_portfolio

    portfolio = build_portfolio(wl, reg_log)
    typer.echo(f"Portfolio ({len(portfolio.rows)} events):\n")
    for row in portfolio.rows:
        typer.echo(f"  {row.name}  [{row.event_id}]")
        typer.echo(
            f"    target {row.target_qty} | registered {row.registered} | "
            f"won {row.won} | secured {row.secured}"
        )


# ---------------------------------------------------------------------------
# Lottery ledger
# ---------------------------------------------------------------------------


@app.command()
def register(
    event_id: Annotated[str, typer.Argument(help="Event id")],
    person: Annotated[str, typer.Argument(help="Person's name (must be in roster)")],
    presale: Annotated[str, typer.Option("--presale", help="Presale name")] = "Verified Fan",
    deadline: Annotated[
        str | None, typer.Option("--deadline", help="Registration deadline, ISO")
    ] = None,
) -> None:
    """Record that a person registered for an event's lottery or presale."""
    _setup_logging(False)
    roster = load_roster()
    if roster.find(person) is None:
        typer.echo(f"'{person}' is not in the roster. Add them first.", err=True)
        raise typer.Exit(1)

    from ticketman.registry import register as do_register

    reg_log = load_registrations()
    do_register(
        reg_log, person, event_id, presale_name=presale, deadline=_parse_when(deadline)
    )
    save_registrations(reg_log)
    typer.echo(f"Recorded: {person} registered for {event_id} ({presale}).")


@app.command()
def result(
    event_id: Annotated[str, typer.Argument(help="Event id")],
    person: Annotated[str, typer.Argument(help="Person's name")],
    won: Annotated[bool, typer.Option("--won/--lost", help="Lottery outcome")] = False,
    window_start: Annotated[
        str | None, typer.Option("--window-start", help="Purchase window start, ISO")
    ] = None,
    window_end: Annotated[
        str | None, typer.Option("--window-end", help="Purchase window end, ISO")
    ] = None,
) -> None:
    """Record a person's lottery outcome and, if they won, their buy window."""
    _setup_logging(False)

    from ticketman.registry import record_result

    reg_log = load_registrations()
    record_result(
        reg_log,
        person,
        event_id,
        won=won,
        window_start=_parse_when(window_start),
        window_end=_parse_when(window_end),
    )
    save_registrations(reg_log)
    outcome = "WON" if won else "lost"
    typer.echo(f"Recorded: {person} {outcome} for {event_id}.")


@app.command()
def purchased(
    event_id: Annotated[str, typer.Argument(help="Event id")],
    person: Annotated[str, typer.Argument(help="Person's name")],
    quantity: Annotated[int, typer.Option("--quantity", "-q", help="Tickets bought")] = 0,
) -> None:
    """Record that a winner completed their purchase."""
    _setup_logging(False)

    from ticketman.registry import record_purchase

    reg_log = load_registrations()
    try:
        record_purchase(reg_log, person, event_id, qty=quantity)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    save_registrations(reg_log)
    typer.echo(f"Recorded: {person} bought {quantity} for {event_id}.")


@app.command()
def board(
    event_id: Annotated[
        str | None, typer.Argument(help="Event id, or omit for the whole portfolio")
    ] = None,
) -> None:
    """War-room view: registrations, wins, purchase windows, and assignments."""
    _setup_logging(False)
    wl = load_watchlist()
    reg_log = load_registrations()
    roster = load_roster()

    from ticketman.board import build_event_board, build_portfolio, resolve_timezone

    if event_id is None:
        portfolio = build_portfolio(wl, reg_log)
        if not portfolio.rows:
            typer.echo("Nothing tracked yet. Add events with 'ticketman watchlist add'.")
            return
        typer.echo("PORTFOLIO BOARD\n")
        for row in portfolio.rows:
            gap = max(0, row.target_qty - row.secured)
            state = "DONE" if gap == 0 else f"need {gap} more"
            typer.echo(f"  {row.name}  [{row.event_id}]")
            typer.echo(
                f"    registered {row.registered} | won {row.won} | "
                f"secured {row.secured}/{row.target_qty}  ({state})"
            )
        return

    entry = wl.find(event_id)
    name = entry.name if entry else event_id
    target = entry.target_qty if entry else 4
    b = build_event_board(event_id, name, target, reg_log)

    typer.echo(f"BOARD: {b.name}  [{b.event_id}]")
    typer.echo(
        f"registered {b.registered_count} | won {b.won_count} | "
        f"secured {b.secured_qty}/{b.target_qty} | still need {b.remaining}\n"
    )

    if not b.registrations:
        typer.echo("No one registered yet. Use 'ticketman register'.")
        return

    for r in b.registrations:
        tz = resolve_timezone(roster, r.participant)
        line = f"  {r.participant:<18} {r.status:<10}"
        if r.status == "won":
            line += (
                f" window {_fmt_dt(r.purchase_window_start, tz)}"
                f" to {_fmt_dt(r.purchase_window_end, tz)}"
            )
        elif r.status == "purchased":
            line += f" bought {r.purchased_qty}"
        typer.echo(line)

    if b.assignments:
        typer.echo("\nASSIGNMENTS (buy in your window, then everyone else stands down):")
        for a in b.assignments:
            typer.echo(f"  {a.participant}: buy {a.quantity}")
    elif b.remaining > 0:
        typer.echo("\nNo winners yet to assign. Waiting on lottery results.")


# ---------------------------------------------------------------------------
# Calendar export
# ---------------------------------------------------------------------------


@app.command()
def calendar(
    out: Annotated[Path, typer.Option("--out", help="Output .ics path")] = Path("ticketman.ics"),
    config_path: ConfigOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Export all deadlines and sale windows to an .ics calendar file.

    Fetches each watchlist event for its live sale schedule, and adds any
    registration deadlines and won purchase windows already recorded.
    """
    _setup_logging(verbose)
    cfg = load_config(config_path)
    wl = load_watchlist()
    reg_log = load_registrations()

    if not wl.events:
        typer.echo("Watchlist is empty. Add events with 'ticketman watchlist add'.")
        raise typer.Exit(1)

    from datetime import datetime as _dt

    from ticketman.ics import CalEvent, render_calendar

    cal_events: list[CalEvent] = []
    with _client(cfg) as client:
        for entry in wl.events:
            try:
                e = client.get_event(entry.event_id)
            except Exception as exc:
                typer.echo(f"Skipping {entry.event_id}: {exc}", err=True)
                continue
            for ps in e.presales:
                if ps.start:
                    cal_events.append(
                        CalEvent(
                            uid=f"{e.id}-presale-{ps.name}@ticketman",
                            summary=f"Presale: {e.name} ({ps.name})",
                            start=ps.start,
                            end=ps.end,
                            description=e.url,
                        )
                    )
            if e.public_sale and e.public_sale.start:
                cal_events.append(
                    CalEvent(
                        uid=f"{e.id}-onsale@ticketman",
                        summary=f"On-sale: {e.name}",
                        start=e.public_sale.start,
                        end=e.public_sale.end,
                        description=e.url,
                    )
                )

    for r in reg_log.registrations:
        if r.registration_deadline:
            cal_events.append(
                CalEvent(
                    uid=f"{r.event_id}-deadline-{r.participant}@ticketman",
                    summary=f"Registration deadline: {r.participant} ({r.event_id})",
                    start=r.registration_deadline,
                )
            )
        if r.status == "won" and r.purchase_window_start:
            cal_events.append(
                CalEvent(
                    uid=f"{r.event_id}-buywindow-{r.participant}@ticketman",
                    summary=f"BUY WINDOW: {r.participant} ({r.event_id})",
                    start=r.purchase_window_start,
                    end=r.purchase_window_end,
                )
            )

    if not cal_events:
        typer.echo("No dated windows or deadlines to export yet.")
        raise typer.Exit(1)

    ics_text = render_calendar(cal_events, stamp=_dt.now(UTC))
    out.write_text(ics_text, encoding="utf-8")
    typer.echo(f"Wrote {len(cal_events)} calendar entries to {out}.")


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


@outcome_app.command("set")
def outcome_set(
    event: Annotated[str, typer.Argument(help="Event URL or id")],
    sold_out: Annotated[bool, typer.Option("--sold-out/--not-sold-out")] = True,
    minutes: Annotated[
        int | None, typer.Option("--minutes", help="Minutes to sell out, if known")
    ] = None,
    config_path: ConfigOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Label a past event as sold out or not, caching its current score."""
    _setup_logging(verbose)
    cfg = load_config(config_path)
    with _client(cfg) as client:
        e = client.get_event(event)

    from ticketman.models import EventOutcome
    from ticketman.strategy import score_sellout

    score = score_sellout(e, cfg.strategy).score
    ol = load_outcomes()
    existing = ol.find(e.id)
    if existing:
        existing.sold_out = sold_out
        existing.minutes_to_sellout = minutes
        existing.score = score
        existing.name = e.name
    else:
        ol.outcomes.append(
            EventOutcome(
                event_id=e.id,
                name=e.name,
                sold_out=sold_out,
                minutes_to_sellout=minutes,
                score=score,
            )
        )
    save_outcomes(ol)
    label = "sold out" if sold_out else "did not sell out"
    typer.echo(f"Labeled {e.name}: {label} (cached score {score:.0f}).")


@app.command()
def calibrate() -> None:
    """Report how well the sellout score matches your labeled outcomes."""
    _setup_logging(False)
    ol = load_outcomes()

    from ticketman.calibrate import calibrate as run_calibrate

    result = run_calibrate(ol.outcomes)
    typer.echo("CALIBRATION")
    typer.echo(f"  labeled events: {result.n}  (sold out: {result.n_sold_out})")
    if result.overall_auc is None:
        typer.echo("  AUC: n/a")
    else:
        typer.echo(f"  AUC (sold-out ranked above rest): {result.overall_auc:.2f}")
    for note in result.notes:
        typer.echo(f"  - {note}")


if __name__ == "__main__":
    app()
