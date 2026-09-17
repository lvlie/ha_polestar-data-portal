# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-09-17

A review pass over the integration from four angles — an installing user, a
security adviser, a test engineer and a Home Assistant maintainer — plus a
shorter README.

### Security

- **Data requests no longer follow redirects.** Every vehicle request carries
  the bearer token in an `Authorization` header, and aiohttp follows redirects
  by default, so a `302` from the API host would have replayed that token to
  whatever host the response named. Redirects are now refused and reported;
  the token request already refused them.
- **The VIN no longer reaches the log when a poll fails completely.** Every
  other path masks it, but the message raised when no domain answers embedded
  the full VIN, and Home Assistant logs that message verbatim.

### Fixed

- **Re-authenticating with another account's credentials is refused.** It
  previously rebound the entry silently, leaving its devices and history
  pointing at vehicles the new credential cannot read.
- **Clearing the optional delegated account during re-authentication now
  sticks.** The form shows every stored value, but an emptied field was merged
  away instead of applied.
- **A blank required field reports a form error** instead of failing the flow
  with an unhandled error. The frontend blocks this; the websocket API does
  not.
- **Deleting the integration removes its discovery cache.** The cached vehicle
  and scope list stayed in Home Assistant's storage after the entry was gone.

### Changed

- A duplicate account is rejected before its credentials are validated, so
  adding one twice costs nothing from the daily request allowance.
- The README is about a fifth shorter: the per-entity list of what starts
  disabled moved into a collapsible section, and the duplicated explanations
  of VIN handling were merged.

### Added

- Tests for each of the above, each verified to fail against the previous
  behaviour: that both the token and data requests set `allow_redirects=False`
  and that a `3xx` is reported rather than parsed, that a totally failed poll
  masks the VIN, that re-auth across accounts aborts, that the delegated
  account can be cleared, and that removing the entry clears its cache.
- `test_token_request_does_not_follow_redirects` now asserts the redirect
  setting it is named for. It previously only re-checked that the token URL
  was `https`.

### Removed

- The unused `short_vin` helper and its test, the unused `base_url` property,
  and two unused enum constants.

## [0.1.1] - 2026-09-17

Follow-up to 0.1.0, from re-checking the integration against the same car once
it had stopped charging. The API turns out to omit more than empty
collections: it drops scalar fields too, whenever their value is falsy.

### Fixed

- **Charging power, current and voltage read `unknown` while not charging.**
  A car actively charging reports all three; the same car on a scheduled
  charge sends none of them. They now read `0`, which is both the true value
  and what a measurement sensor needs to avoid gaps in its history and in the
  energy dashboard. An explicitly null value still reads unknown, since that
  is the API saying it does not know.
- **`Charge now` read `unknown` once switched off.** The override flag is
  present while it is on and omitted entirely when off; an absent flag inside
  a payload that did arrive now reads `off`.

### Added

- A second recorded fixture for the same vehicle with its charge scheduled
  rather than running, and tests asserting a parked car produces no new
  unknown entities. Every value in it is synthetic.

## [0.1.0] - 2026-09-17

First release validated against a real vehicle rather than only against the
published OpenAPI specification. A 2022 Polestar 2 turned up four parsing bugs
and a large number of entities that could never populate on that model.

### Fixed

- **Charging-settings timestamps were never parsed.** `updatedAt` on the
  charging endpoints is epoch milliseconds in a string (`"1789558748374"`),
  not ISO 8601 as assumed. The spec types the field as a bare string, so only
  real traffic revealed it. *Charging current limit updated* and *Arrived at
  charge location* sat at unknown as a result.
- **Timers set on the hour were unreadable.** The API omits whichever half of
  a time is zero, so an 08:00 timer arrives as `{"hour": 8}` with no `minute`.
  A missing component now means zero instead of unknown.
- **Empty collections read as unknown instead of empty.** The API leaves the
  key out entirely when a collection holds nothing, so *Charge locations*
  showed unknown rather than `0`, and *Climatization error* and *Climatization
  warning* showed unknown rather than `off` on a car with nothing wrong.
- Enum values that the API adds after this spec was captured no longer reach
  the state machine, where Home Assistant would reject them; they read as
  unknown instead.

### Changed

- **Far fewer entities are enabled by default: 70 of 194, down from 97.**
  Everything remains registered, so enabling any of them is a single click.
  Newly off by default:
  - Tyre pressures and their warnings (10). Older models do not report tyre
    pressure at all, and the models that do drift with tyre temperature all
    day.
  - Values that only exist during an active session: parking-climatisation
    temperatures, start reason and start/end times; cabin pre-cleaning air
    quality, particulate matter, error and start reason.
  - Values that only appear after a completed charge: consumption and trip
    figures since last charge, and total energy consumption.
  - Battery preconditioning status, parking climate timer settings, and the
    sunroof, none of which every model reports.
- The credential form now lists fields in the order the Data Portal credential
  page presents them: app client ID, expected `x-client-id` header, client
  secret, M2M token endpoint. The two middle fields are easy to confuse and
  the previous order forced jumping back and forth.
- Brand icons now come from
  [home-assistant/brands](https://github.com/home-assistant/brands/tree/master/custom_integrations/polestar_api)
  instead of placeholder artwork.

### Added

- A regression test suite built from a real vehicle's payload, asserting that
  no entity enabled by default sits at unknown on that car.

## [0.0.1] - 2026-09-17

Initial release.

> Released as tag `0.0.1`. The `manifest.json` bundled in that tag reads
> `0.1.0` by mistake, so Home Assistant's diagnostics report `0.1.0` while
> HACS reports the release tag `0.0.1`. Both refer to this release. The
> mismatch is corrected from `0.1.0` onwards.

### Added

- Home Assistant integration for the official Polestar Data Portal M2M API,
  the EU Data Act interface, covering all 15 documented telemetry and charging
  domains as roughly 194 entities per vehicle.
- Config flow taking the four values from the Data Portal credential page,
  plus an optional delegated account for third-party credentials, validated at
  setup by requesting a token and listing vehicles.
- Re-authentication flow. The API publishes no credential rotation endpoint,
  so an expired credential must be replaced by hand; this avoids losing entity
  history when that happens.
- Entities typed to Home Assistant conventions: openings and locks as binary
  sensors, warnings as problem sensors that keep the exact severity in an
  attribute, statuses as translated enum sensors, position as a device tracker.
- Per-vehicle discovery of which API domains a credential and car can actually
  read. Endpoints that answer nothing create no entities and cost no requests.
- Polling sized against the documented 10,000 requests per day: the default
  interval scales with the number of vehicles, discovery is cached for seven
  days so restarts stay cheap, and the interval is configurable.
- Diagnostics that redact credentials, VINs, coordinates and charge-location
  names.

[0.2.0]: https://github.com/lvlie/ha_polestar-data-portal/releases/tag/0.2.0
[0.1.1]: https://github.com/lvlie/ha_polestar-data-portal/releases/tag/0.1.1
[0.1.0]: https://github.com/lvlie/ha_polestar-data-portal/releases/tag/0.1.0
[0.0.1]: https://github.com/lvlie/ha_polestar-data-portal/releases/tag/0.0.1
