<p align="center">
  <img src="custom_components/polestar_data_portal/brand/icon.png" alt="Polestar" width="120">
</p>

<h1 align="center">Polestar Data Portal for Home Assistant</h1>

<p align="center">
  Read your Polestar's telemetry in Home Assistant through Polestar's
  <strong>official</strong> EU Data Act API &mdash; no reverse engineering, no app credentials.
</p>

<p align="center">
  <a href="https://github.com/lvlie/ha_polestar-data-portal/actions/workflows/test.yml"><img alt="Tests" src="https://github.com/lvlie/ha_polestar-data-portal/actions/workflows/test.yml/badge.svg"></a>
  <a href="https://github.com/lvlie/ha_polestar-data-portal/actions/workflows/validate.yml"><img alt="Validate" src="https://github.com/lvlie/ha_polestar-data-portal/actions/workflows/validate.yml/badge.svg"></a>
  <a href="https://github.com/lvlie/ha_polestar-data-portal/actions/workflows/ha-compatibility.yml"><img alt="Home Assistant compatibility" src="https://github.com/lvlie/ha_polestar-data-portal/actions/workflows/ha-compatibility.yml/badge.svg"></a>
  <br>
  <a href="https://github.com/hacs/integration"><img alt="HACS" src="https://img.shields.io/badge/HACS-custom-41BDF5.svg"></a>
  <a href="https://github.com/lvlie/ha_polestar-data-portal/releases"><img alt="Release" src="https://img.shields.io/github/v/release/lvlie/ha_polestar-data-portal?display_name=tag&sort=semver"></a>
  <a href="https://www.home-assistant.io/"><img alt="Home Assistant" src="https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5.svg"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/lvlie/ha_polestar-data-portal"></a>
  <br>
  <a href="https://github.com/lvlie/ha_polestar-data-portal/issues"><img alt="Issues" src="https://img.shields.io/github/issues/lvlie/ha_polestar-data-portal"></a>
  <a href="https://github.com/lvlie/ha_polestar-data-portal/commits/master"><img alt="Last commit" src="https://img.shields.io/github/last-commit/lvlie/ha_polestar-data-portal"></a>
  <img alt="Maintained" src="https://img.shields.io/badge/maintained-yes-brightgreen.svg">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=lvlie&repository=ha_polestar-data-portal&category=integration"><img alt="Add repository to HACS" src="https://my.home-assistant.io/badges/hacs_repository.svg"></a>
  <a href="https://my.home-assistant.io/redirect/config_flow_start/?domain=polestar_data_portal"><img alt="Add integration to Home Assistant" src="https://my.home-assistant.io/badges/config_flow_start.svg"></a>
</p>

---

> [!IMPORTANT]
> **EU and EEA only.** The Polestar Data Portal exists because of the
> [EU Data Act](https://digital-strategy.ec.europa.eu/en/policies/data-act),
> which gives users of connected products access to the data their product
> generates. Polestar offers it to owners and users of vehicles **registered
> and delivered in the EU or EEA**. If your car was delivered outside that
> area you cannot create credentials, and this integration has nothing to
> talk to.

> [!NOTE]
> Unofficial and community-maintained. Not built, endorsed, supported or
> reviewed by Polestar. See [Disclaimer](#disclaimer).

## What you get

One device per vehicle, with an entity for every field the Data Portal
publishes: **194 per car, 70 enabled by default**.

| Area | Examples |
| --- | --- |
| **Battery & charging** | State of charge, range, charging status, power/current/voltage, time to full, charge limit, current limit, charge timers, Charge Now |
| **Odometer & trips** | Odometer, three trip meters, average speeds, average and total consumption |
| **Location** | `device_tracker` with GPS position, plus speed, heading and altitude |
| **Doors & security** | Four doors, four windows, sunroof, hood, tailgate, charge port, central lock, tailgate lock, alarm |
| **Health** | Brake fluid, coolant, oil, washer fluid, 12V battery, service interval, 40 exterior lights plus one aggregate failure sensor, four tyre pressures and their warnings |
| **Climate** | Parking climatization, cabin temperature, ventilation, seat and steering wheel heating, climate timers |
| **Cabin air** | Pre-cleaning state, air quality index, PM2.5 |
| **Availability** | Availability status, usage mode, per-domain data freshness |

Everything is typed the way Home Assistant expects: doors and windows carry
door/window device classes, warnings are `problem` sensors keeping the exact
severity in a `state` attribute, statuses are enum sensors with translated
options, and the position is a real `device_tracker`.

**The integration only reads.** The Data Portal publishes no write endpoints,
so nothing here can lock, unlock or start your car.

### Why 124 entities start disabled

Not every model reports every field, and the ones yours does not report would
sit at *unknown* forever. Anything narrow, noisy or model-dependent is
registered but switched off, so you can turn on exactly what your car answers.

To enable one: **Settings → Devices & services → Polestar Data Portal →
entities**, filter by *Disabled*, pick it and switch it on.

<details>
<summary>What is disabled, and why</summary>

- **Tyre pressures and their warnings** (10). Older models do not report them
  at all, and where they are reported the reading drifts with tyre temperature
  during a drive.
- **Per-bulb light warnings** (40), covered by the aggregate *Exterior light
  failure* sensor, which is on by default.
- **Per-category energy consumption breakdowns** (24).
- **Values that only exist during an active session**: parking-climatisation
  temperatures, start reason and start/end times; cabin pre-cleaning air
  quality, particulate matter, error and start reason.
- **Values that only appear after a completed charge**: consumption and trip
  figures since the last charge, and total energy consumption.
- **Battery preconditioning, parking climate timer settings and the sunroof**,
  which not every model reports.
- **Pending and deprecated fields**, mirroring a setting the car has not
  confirmed yet or one Polestar has superseded.

</details>

## Install

Requires Home Assistant 2025.1+, a Polestar delivered in the EU or EEA, and a
free Data Portal account.

1. Click **Add repository to HACS** above, or add
   `https://github.com/lvlie/ha_polestar-data-portal` manually as a custom
   repository of type *Integration*.
2. Install **Polestar Data Portal** and restart Home Assistant.
3. Click **Add integration to Home Assistant** above, or find *Polestar Data
   Portal* under **Settings → Devices & services → Add integration**.

To install by hand instead, copy `custom_components/polestar_data_portal` into
your `config/custom_components/` directory and restart.

> [!NOTE]
> HACS's update card shows no icon: it loads that one image from the brands
> CDN, which no longer accepts new custom integrations. Home Assistant's own
> pages use the icon shipped in this repository.

## Credentials

1. Sign in at **<https://data-portal.polestar.com>**. Start from that address
   rather than a country link: the URL differs per market (the Dutch one is
   `https://data-portal.polestar.com/nl/api-credentials/credential`), and
   signing in from the root sends you to the right one.
2. Go to **Data Portal API → Credential** and create one, granting the scopes
   you want to read. The integration discovers which scopes you granted and
   only creates entities for those.
3. Copy four values into the Home Assistant setup form:

| Setup field | Where it comes from |
| --- | --- |
| **App client ID** | The *App client ID* on the credential page |
| **Expected x-client-id header** | Your account ID &mdash; **not** the same as the App client ID |
| **Client secret** | Shown **once**, when the credential is created |
| **M2M token endpoint** | The *M2M Token Endpoint* on the credential page |

A fifth field, *Delegated account e-mail*, is optional. Leave it empty unless
you hold third-party credentials and want to read vehicles shared with you by
another account in the same company domain.

> [!WARNING]
> The client secret is shown only at creation time. If you lose it, create a
> new credential — it cannot be recovered.

**Credentials cannot be rotated programmatically.** The published spec defines
exactly one credential operation, `POST /token`; there is no renewal endpoint,
so an expired or revoked credential has to be recreated by hand in the portal.
The integration raises a re-authentication prompt when that happens, and you
paste the new values in without losing history or automations.

## Naming

The Data Portal publishes no model, trim or nickname — `/v1/vehicles` returns
bare VINs — so the integration cannot tell a Polestar 2 from a Polestar 4 and
picks a neutral default instead:

| Vehicles on the account | Device name | Entity IDs |
| --- | --- | --- |
| One | `Polestar` | `sensor.polestar_battery` |
| Several | `Polestar 123456` | `sensor.polestar_123456_battery` |

The suffix is the shortest part of the VIN that is unique across the account,
taken from every VIN on it so a car that temporarily loses a scope cannot
rename the others.

**To get `sensor.polestar_2_*`, rename the device** (Settings → Devices &
services → the device → pencil icon). Home Assistant offers to update every
entity ID to match, which is safe here: unique IDs are built from the VIN, not
the name, so history, statistics and automations follow along.

## API request budget

Polestar allows roughly **10,000 requests per day**. One refresh costs one
request per data domain per vehicle, so:

- **Default 15 minutes** — about 1,460 requests/day for one car reading all 15
  domains — **raised automatically** when a larger fleet would overrun the
  budget (a ten-vehicle account starts at 24 minutes).
- **Restarts are cheap.** Which endpoints your credential can read is
  discovered once and cached for seven days, so a restart loop re-reads only
  your domains instead of probing all fifteen.
- **Access tokens are reused** until shortly before they expire.

Change the interval under **Settings → Devices & services → Polestar Data
Portal → Configure**. Your choice is always honoured; one that exceeds the
allowance logs a warning naming an interval that fits. Saving options also
clears the discovery cache, which is the supported way to pick up a new
vehicle or a newly granted scope.

## Privacy and credentials

- **Credentials live in Home Assistant's config entry storage**, like every
  other integration. That store is not encrypted, so treat your configuration
  directory and your backups as sensitive.
- **The token endpoint must use `https`**, because the client secret travels
  in the request body. Neither the token request nor any data request follows
  redirects, so no secret or bearer token is replayed to a host the server
  picks.
- **Nothing secret is logged.** Even at debug level the client ID, secret,
  account ID and access token never reach the log — enforced by a test that
  runs a full setup with debug logging on and asserts their absence.
- **VINs are masked in logs** as `****1234`, on error paths too. The full VIN
  stays on the device as its serial number and in each entity's unique ID.
- **Diagnostics are redacted** — credentials, VINs, coordinates and
  charge-location names — so the download can go straight onto an issue.
- **Location data stays local.** The integration reads from Polestar and
  writes to Home Assistant; it sends nothing anywhere else.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest
.venv/bin/pre-commit run --all-files
```

[`resources/openapi.json`](resources/openapi.json) is a copy of the spec
published at
`https://data-portal.polestar.com/<market>/api-credentials/docs/openapi`, and
it is not decoration:

- `enums.py` and `translations/en.json` are **generated** from it, by
  `scripts/generate_enums.py` and `scripts/generate_translations.py`.
  `scripts/check_generated.py` fails the build if either drifts; pre-commit
  runs it for you.
- Every mocked API response in the tests is built from it, so an upstream
  schema change surfaces as a failing test, not a silently broken sensor.
- CI runs the real client against a
  [Prism](https://github.com/stoplightio/prism) mock of the same file
  (`scripts/prism_contract_check.py`), which validates every request against
  the spec, then boots the integration against that mock inside a real Home
  Assistant container (`scripts/ha_smoke.py`).

To update the spec, replace the file and run the two generators and the tests.

The icons in `custom_components/polestar_data_portal/brand/` are not
generated. Since Home Assistant 2026.3 a custom integration serves its own
icon from that directory, which is how this one has an icon without an entry
in the brands CDN.

## Disclaimer

This project is provided **as is, without warranty of any kind**, express or
implied, including but not limited to the warranties of merchantability,
fitness for a particular purpose and non-infringement. In no event shall the
authors or copyright holders be liable for any claim, damages or other
liability arising from, out of, or in connection with the software or its use.
See [LICENSE](LICENSE) for the full terms.

By using this integration you accept that:

- You are responsible for your own use of the Polestar Data Portal, including
  its terms of service and its request limits. Exceeding them may get your
  credential throttled or revoked.
- You are responsible for keeping your own credentials safe.
- Vehicle location and telemetry are personal data. What you do with them once
  they are in Home Assistant — storing, forwarding, sharing — is your
  responsibility.
- The maintainers are volunteers. Nothing here is a service, and there is no
  guarantee it keeps working if Polestar changes the API.

You agree to hold the maintainers harmless from any claim arising out of your
use of this integration or of the Polestar Data Portal through it.

**Polestar** is a trademark of Polestar Performance AB. This project is not
affiliated with, authorised by, or connected to Polestar in any way. The icon
shipped in this repository is Polestar's mark, taken from the
[Home Assistant brands repository](https://github.com/home-assistant/brands/tree/master/custom_integrations/polestar_api).
It identifies which vehicle the integration talks to and implies no
endorsement by Polestar.

## Credits

- [evcc](https://github.com/evcc-io/evcc) mapped this API for their own client
  first; their MIT-licensed work was a useful cross-check. No evcc code is
  included here.
- [pypolestar](https://github.com/pypolestar/polestar_api) covers Polestar's
  older, unofficial consumer API, which this integration deliberately does not
  use.

## License

[MIT](LICENSE)
