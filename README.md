# ticketman

A command-line tool that helps you and a group of friends land 3 to 5 retail
concert tickets on Ticketmaster, by getting everyone prepped and pointed at the
right sale window at the right second.

It is not a checkout bot. It never logs in, solves a CAPTCHA, sits in the queue,
or clicks buy. It reads Ticketmaster's official event data and keeps your group
organized. Every purchase is made by a real person, by hand, on their own
account.

## Contents

- [Install and setup](#install-and-setup)
- [How it fits together](#how-it-fits-together)
- [Quickstart](#quickstart)
- [Workflow A: size up one show](#workflow-a-size-up-one-show)
- [Workflow B: run a group Verified Fan lottery](#workflow-b-run-a-group-verified-fan-lottery)
- [Command reference](#command-reference)
- [The sellout score](#the-sellout-score)
- [Configuration](#configuration)
- [Where your data lives](#where-your-data-lives)
- [Limitations](#limitations)
- [Development](#development)

## Install and setup

1. Get a free Discovery API key at https://developer.ticketmaster.com. Create an
   app; the value labeled "Consumer Key" is your key. It is read-only event data.

2. Give ticketman the key. Exporting it is preferred:

   ```bash
   export TM_API_KEY="your-consumer-key"
   ```

   Or copy `config/config.example.yaml` to `config/config.yaml` and set
   `ticketmaster.api_key`.

3. Install. This project uses `uv` for its Python environment.

   ```bash
   make setup      # creates .venv and installs with dev dependencies
   ```

   After that, run the tool as `ticketman ...` inside the activated `.venv`, or
   directly as `.venv/Scripts/ticketman` on Windows.

Check that the key is picked up:

```bash
ticketman status
```

## How it fits together

Five pieces of state, four of which you build up as you go. Understanding these
makes every command obvious.

- **Roster**: the real people in your buying group. Each has a name, an account
  email, an optional timezone, and access tags (like `amex` or `verified-fan`).
  One account per person. No passwords are stored.
- **Watchlist**: the events you are actively coordinating (your portfolio). Each
  entry caches the event name and your target ticket count.
- **Registrations**: one record per person per event, tracking the lottery
  lifecycle: `intend` to `registered` to `won` or `lost` to `purchased`.
- **Outcomes**: past events you have labeled as sold out or not, used to check
  whether the sellout score is any good.
- **Config**: your API key and the sellout-score weights.

The `board` command reads the roster, watchlist, and registrations together to
show you, at a glance, who won and who should buy what.

## Quickstart

```bash
# 1. Find a show and copy its event id.
ticketman find "artist name" --city Boston

# 2. See its full sale schedule and prices.
ticketman info 0B00612D7C1E5A3F

# 3. Score how likely it is to sell out, and get a plan.
ticketman plan 0B00612D7C1E5A3F --quantity 4
```

That is the research loop. The rest of the tool is about coordinating a group
through the sale, covered next.

## Workflow A: size up one show

Use this the moment a show is announced, to decide how hard to fight for it.

```bash
ticketman info 0B00612D7C1E5A3F      # when do presales and the on-sale open
ticketman plan 0B00612D7C1E5A3F      # sellout risk with a full factor breakdown
ticketman checklist 0B00612D7C1E5A3F # what each person should do before the sale
```

`plan` prints a sellout score from 0 to 100 with every contributing factor, then
tells you which window to target. If risk is High or Extreme, commit to the
earliest presale instead of waiting for the public on-sale, because inventory
thins with each window.

## Workflow B: run a group Verified Fan lottery

This is the core of the tool: a group of real friends, each on their own
account, each buying their own tickets. More real registrations means more
lottery entries and a backup if one person's code does not work.

```bash
# 1. Build the group. Repeat per friend. One real person per account.
ticketman roster add "Joe" --email joe@example.com --timezone America/New_York --access verified-fan,amex
ticketman roster add "Amy" --email amy@example.com --timezone America/Chicago  --access verified-fan

# 2. Track the event and set the group's total target.
ticketman watchlist add 0B00612D7C1E5A3F --quantity 4

# 3. Record who registered for the Verified Fan draw, with the deadline.
ticketman register 0B00612D7C1E5A3F Joe --deadline 2026-04-25T23:59
ticketman register 0B00612D7C1E5A3F Amy --deadline 2026-04-25T23:59

# 4. Put every deadline and window on your calendar.
ticketman calendar --out ticketman.ics

# 5. When codes go out, record outcomes and the buy window winners were given.
ticketman result 0B00612D7C1E5A3F Joe --won --window-start 2026-05-01T10:00 --window-end 2026-05-01T12:00
ticketman result 0B00612D7C1E5A3F Amy --lost

# 6. Check the board. It tells you who buys, how many, without overbuying.
ticketman board 0B00612D7C1E5A3F

# 7. Log the purchase once it is done.
ticketman purchased 0B00612D7C1E5A3F Joe --quantity 4
```

`board <event-id>` looks like this:

```
BOARD: Big Act - Live  [0B00612D7C1E5A3F]
registered 2 | won 1 | secured 0/4 | still need 4

  Amy                lost
  Joe                won        window Fri May 01, 2026 10:00 AM EDT to Fri May 01, 2026 12:00 PM EDT

ASSIGNMENTS (buy in your window, then everyone else stands down):
  Joe: buy 4
```

Run `board` with no event id for a portfolio roll-up across every tracked show.

## Command reference

Common options: `--config, -c PATH` points at an alternate config file;
`--verbose, -v` turns on debug logging. Any command that reaches Ticketmaster
needs `TM_API_KEY` set.

### Research

**`ticketman find KEYWORD [--city CITY] [--size N]`**
Search events by keyword. Prints each match with its event id, date, venue,
status, and on-sale time. `--size` caps results (default 15).

**`ticketman info EVENT`**
Show one event's full sale schedule (every presale plus the public on-sale) and
price range. `EVENT` is a Ticketmaster URL or a bare event id.

**`ticketman plan EVENT [--quantity N]`**
Score sellout risk with a per-factor breakdown, list the sale windows soonest
first, mark which people in your roster can access each presale, and recommend a
group plan for `N` tickets (default 4).

**`ticketman checklist EVENT`**
Print a prep checklist, plus a per-person view of who is eligible for which
presale.

**`ticketman watch EVENT [--interval SECONDS]`**
Poll one event and fire a desktop alert when a presale or the public on-sale
opens, when the status flips to onsale, or when the price range drops. Polls
every 60 seconds by default; values under 30 are clamped to avoid rate limits.
Runs until you press Ctrl-C.

### Roster

**`ticketman roster add NAME [--email E] [--city C] [--timezone TZ] [--access TAGS] [--notes N]`**
Add or update a person. `--timezone` takes an IANA name like `America/New_York`
and controls how their purchase windows render on the board. `--access` is a
comma-separated tag list (`amex,citi,fan-club,verified-fan`) used to match them
to presales. If two people end up sharing an email, the command warns you.

**`ticketman roster list`** shows everyone. **`ticketman roster remove NAME`**
removes a person.

### Portfolio (watchlist)

**`ticketman watchlist add EVENT [--quantity N] [--notes N]`**
Fetch an event and add it to the portfolio with a target of `N` tickets
(default 4). Re-running updates the target.

**`ticketman watchlist list`** shows the portfolio with per-event registration
counts. **`ticketman watchlist remove EVENT_ID`** drops an entry.

### Lottery ledger

**`ticketman register EVENT_ID PERSON [--presale NAME] [--deadline ISO]`**
Record that a person registered for an event's presale or Verified Fan draw. The
person must already be in the roster. `--presale` defaults to `Verified Fan`.

**`ticketman result EVENT_ID PERSON --won|--lost [--window-start ISO] [--window-end ISO]`**
Record a lottery outcome. On a win, pass the purchase window they were given.

**`ticketman purchased EVENT_ID PERSON --quantity N`**
Record a completed purchase, so the board knows the target is met.

**`ticketman board [EVENT_ID]`**
With an event id, the war-room view: every person's status, each winner's
purchase window in their own timezone, and who is assigned to buy how many.
Without an argument, a roll-up across the whole portfolio.

### Calendar

**`ticketman calendar [--out PATH]`**
Fetch every watchlist event's live sale schedule, add any recorded registration
deadlines and won purchase windows, and write a standard `.ics` file (default
`ticketman.ics`). Import it once into Google or Apple Calendar. Times are stored
in UTC so any calendar app renders them in the viewer's local time.

### Calibration

**`ticketman outcome set EVENT --sold-out|--not-sold-out [--minutes N]`**
Label a past event and cache its score at label time.

**`ticketman calibrate`**
Report how well the score ranked your labeled events (AUC), and warn when the
sample is too small to trust.

### Utility

**`ticketman status`** shows whether the API key is set, the country, and the
roster summary.

Dates are ISO 8601. A naive value like `2026-05-01T14:00` is read as your local
time; add an offset (`2026-05-01T14:00-04:00`) to be explicit.

## The sellout score

No black box. `plan` computes a weighted average of six normalized factors,
rescaled to 0 to 100:

```
final = 100 * sum(weight_i * factor_i) / sum(weight_i)
```

The factors are presale density, Verified Fan or Platinum presence, price
ceiling, market size, venue scarcity, and genre base rate. Each is normalized to
0 to 1 (higher means more likely to sell out), and `plan` prints every factor's
value, weight, contribution, and a short note, so you can see exactly why a show
scored what it did. Tiers: Low (under 30), Moderate (30 to 55), High (55 to 78),
Extreme (78 and up).

The weights live in `config.yaml` under `strategy` and are yours to tune. The
reference tables (market sizes, genre rates) are editable heuristics in
[`src/ticketman/strategy.py`](src/ticketman/strategy.py), not received truth.

To tune against reality: label a handful of past events with `outcome set`, run
`calibrate`, and adjust the weights based on the factor breakdowns you see in
`plan`. Calibration deliberately does not auto-optimize the weights, because a
search over a few labeled events fits noise rather than signal.

## Configuration

`config/config.yaml` (copy from `config/config.example.yaml`):

```yaml
ticketmaster:
  api_key: ""          # or set TM_API_KEY (preferred)
  country_code: "US"
notifications:
  desktop: true
strategy:
  presale_density: 0.25
  verified_fan: 0.25
  price_ceiling: 0.15
  market_size: 0.15
  venue_scarcity: 0.12
  genre: 0.08
```

Precedence is environment variable, then config file, then defaults. The only
secret is the API key.

## Where your data lives

All coordination state is plain YAML under `config/`, and all of it is
gitignored because it contains your group's personal details:

- `config/roster.yaml` the buying group
- `config/watchlist.yaml` tracked events
- `config/registrations.yaml` the lottery ledger
- `config/outcomes.yaml` labeled past events

No passwords are ever stored, in any file. Each participant is treated as a
distinct person; a shared account email triggers a warning, because one person
holding many accounts is the account-farming pattern this tool refuses to
support.

## Limitations

- **Resale is a proxy, not a live feed.** The free Discovery API exposes event
  schedules, status, and price ranges, but not seat-by-seat resale listings with
  individual prices. `watch` alerts on price-range and status changes, which is a
  useful signal but not true listing-level face-value sniping. That would need
  partner API access individuals do not get, and this tool will not scrape the
  site to fake it.
- **No alerting delivery pipeline yet.** `watch` fires desktop toasts for a
  single event. There is no email or multi-event notification system.

## Development

```bash
make lint       # ruff
make test       # pytest with coverage
make sensors    # full gate: lint, tests with coverage floor, bandit, pip-audit
```
