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
> generates. Polestar offers the portal to owners and users of vehicles
> **registered and delivered in the EU or EEA**. If your car was delivered
> outside that area you will not be able to create credentials, and this
> integration will have nothing to talk to.

> [!NOTE]
> This is an **unofficial, community-maintained** project. It is not built,
> endorsed, supported or reviewed by Polestar. See
> [Disclaimer](#disclaimer) before you install it.

## What you get

One device per vehicle, with entities for every field the Data Portal
publishes &mdash; around 190 per car, of which roughly 95 are enabled by
default and the rest (per-bulb light warnings, per-category energy
breakdowns, pending settings) can be switched on from the entity registry
when you need them.

| Area | Examples |
| --- | --- |
| **Battery & charging** | State of charge, range, charging status, charging power/current/voltage, time to full, charge limit, charging current limit, charge timers, Charge Now |
| **Odometer & trips** | Odometer, three trip meters, average speeds, average and total energy consumption |
| **Location** | `device_tracker` with GPS position, plus speed, heading and altitude |
| **Doors & security** | Four doors, four windows, sunroof, hood, tailgate, charge port, central lock, tailgate lock, alarm |
| **Health** | Four tyre pressures and their warnings, brake fluid, coolant, oil, washer fluid, 12V battery, service interval, 40 individual exterior lights plus one aggregate failure sensor |
| **Climate** | Parking climatization state, cabin temperature, ventilation, seat and steering wheel heating, climate timers |
| **Cabin air** | Pre-cleaning state, air quality index, PM2.5 |
| **Availability** | Availability status, usage mode, per-domain data freshness timestamps |

Entities are typed the way Home Assistant expects: doors and windows are
`binary_sensor`s with door/window device classes, warnings are `problem`
sensors that keep the exact severity in a `state` attribute, statuses are
enum sensors with translated options, and the location is a real
`device_tracker` rather than a pair of latitude/longitude sensors.

The integration only reads. The Data Portal publishes no write endpoints, so
nothing here can lock, unlock, or start your car.

## Requirements

- Home Assistant 2025.1 or newer
- A Polestar delivered in the EU or EEA
- A free Polestar Data Portal account with an API credential

## Installation

### HACS (recommended)

1. Click the **Add repository to HACS** button above, or add
   `https://github.com/lvlie/ha_polestar-data-portal` manually as a custom
   repository of type *Integration*.
2. Install **Polestar Data Portal**.
3. Restart Home Assistant.
4. Click **Add integration to Home Assistant** above, or go to
   **Settings → Devices & services → Add integration** and search for
   *Polestar Data Portal*.

### Manual

Copy `custom_components/polestar_data_portal` into your Home Assistant
`config/custom_components/` directory and restart.

## Getting your credentials

1. Sign in at **<https://data-portal.polestar.com>**.
   Start from that address rather than a country-specific link: the URL
   differs per market (the Dutch one is
   `https://data-portal.polestar.com/nl/api-credentials/credential`), and
   signing in from the root sends you to the right one.
2. Navigate to **Data Portal API → Credential**.
3. Create a credential and grant it the scopes you want to read. The
   integration discovers which scopes you granted and only creates entities
   for those.
4. Copy these four values into the Home Assistant setup form:

| Setup field | Where it comes from |
| --- | --- |
| **App client ID** | The *App client ID* on the credential page |
| **Expected x-client-id header** | The *Expected x-client-id header* value &mdash; this is your account ID and is **not** the same as the App client ID |
| **Client secret** | Shown **once**, when the credential is created |
| **M2M token endpoint** | The *M2M Token Endpoint* on the credential page |

There is a fifth, optional field, *Delegated account e-mail*. Leave it empty
unless you hold third-party credentials and want to read vehicles shared with
you by another account in the same company domain.

> [!WARNING]
> The client secret is displayed only at creation time. If you lose it, create
> a new credential &mdash; it cannot be recovered.

### When credentials expire

The published API specification defines exactly one credential operation:
`POST /token`, the client-credentials grant. **There is no rotation or renewal
endpoint**, so credentials cannot be refreshed programmatically; when one
expires or is revoked, a new credential has to be created by hand in the
portal. The integration handles this the Home Assistant way: it raises a
re-authentication prompt instead of failing silently, and you paste the new
values in without losing your entity history or automations.

## Naming

The Data Portal publishes no model, trim or nickname: `/v1/vehicles` returns
bare VIN strings. There is nothing in the API that distinguishes a Polestar 2
from a Polestar 4, so the integration cannot name your car for you.

What it does instead is pick a sensible default and get out of the way:

| Vehicles on the account | Device name | Entity IDs |
| --- | --- | --- |
| One | `Polestar` | `sensor.polestar_battery` |
| Several | `Polestar 123456` | `sensor.polestar_123456_battery` |

With several vehicles the suffix is the shortest part of the VIN that is unique
across your account, so two cars whose serials end in the same digits still get
distinct names. The names come from every VIN on the account, not just the ones
that set up successfully, so a car that temporarily loses a scope cannot rename
the others.

**To get `sensor.polestar_2_*`, rename the device.** Settings → Devices &
services → Polestar Data Portal → the device → the pencil icon. Home Assistant
will offer to update every entity ID to match. This is safe here: entity unique
IDs are built from the VIN, not from the name, so renaming keeps all history,
statistics and automations pointing at the same entities.

## API request budget

Polestar allows roughly **10,000 requests per day**. Every refresh costs one
request per data domain per vehicle, so the integration is careful with them:

- **Default interval: 15 minutes.** For one car reading all 15 domains that is
  about **1,460 requests/day**, well inside the allowance.
- **The default scales with your account.** If you have enough vehicles that
  15 minutes would overrun the budget, the default interval is raised
  automatically. A ten-vehicle account, for instance, starts at 24 minutes.
- **Restarts are cheap.** Discovering which endpoints your credential can read
  costs one request per documented endpoint. That result is cached for seven
  days, so a restart re-reads only the domains you actually have, instead of
  probing all fifteen. This is what keeps a Home Assistant restart loop from
  eating the daily allowance.
- **Access tokens are reused** until shortly before they expire, rather than
  requested per call.

You can change the interval at any time under **Settings → Devices & services
→ Polestar Data Portal → Configure**. Your choice is always honoured; if it
would exceed the documented allowance, a warning is logged with the interval
that would fit. Changing options also clears the discovery cache, which is the
supported way to pick up a newly added vehicle or a newly granted scope.

## The OpenAPI specification

[`resources/openapi.json`](resources/openapi.json) is a copy of the spec
published at
`https://data-portal.polestar.com/<market>/api-credentials/docs/openapi`. It is
not decoration:

- `custom_components/polestar_data_portal/enums.py` is **generated** from it
  (`python3 scripts/generate_enums.py`).
- The tests build every mocked API response from it, so a schema change shows
  up as a failing test rather than a silently broken sensor.
- CI runs the real client against a [Prism](https://github.com/stoplightio/prism)
  mock driven by this same file (`scripts/prism_contract_check.py`). Prism
  validates every request against the spec, so a missing header or a bad auth
  scheme fails the build. It then boots the integration against that mock
  inside a real Home Assistant container.

To update it, replace the file and run:

```bash
python3 scripts/generate_enums.py
python3 scripts/generate_translations.py
python3 -m pytest
```

## Privacy and credentials

This integration handles a credential that can read your car's position, so a
few deliberate choices are worth knowing about:

- **Credentials live in Home Assistant's config entry storage**, the same place
  every other integration keeps them. That store is not encrypted, so treat
  your Home Assistant configuration directory as sensitive and keep your
  backups somewhere safe.
- **The token endpoint must use `https`.** The client secret travels in the
  request body, so a plain `http://` endpoint is refused at setup rather than
  sending the secret in the clear. Redirects are not followed on the token
  request, so the secret is never replayed to a host chosen by the server.
- **Nothing secret is logged.** Even with debug logging on, the client ID,
  client secret, account ID and access token never reach the log. This is
  enforced by a test that runs a full setup with debug logging enabled and
  asserts none of them appear.
- **VINs are masked in logs** as `****1234`, and the device name never carries
  a full VIN (see [Naming](#naming)). Home Assistant writes entity IDs to logs,
  traces and the recorder, so a device named after the whole VIN would spread
  it to places people copy and share. The full VIN is still on the device as
  its serial number and in each entity's unique ID.
- **Diagnostics are redacted.** The downloadable diagnostics strip credentials,
  VINs, coordinates and charge-location names, so the file can be attached to
  an issue as-is.
- **Location data stays local.** The integration only reads from Polestar and
  writes to Home Assistant; it sends nothing anywhere else.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest          # unit and integration tests
.venv/bin/pre-commit run --all-files
```

`scripts/ha_smoke.py` drives a live Home Assistant container against a Prism
mock of the spec; `.github/workflows/test.yml` shows how it is wired up.

Generated files, all rebuilt by their scripts rather than edited by hand:

| File | Script |
| --- | --- |
| `custom_components/polestar_data_portal/enums.py` | `scripts/generate_enums.py` |
| `custom_components/polestar_data_portal/translations/en.json` | `scripts/generate_translations.py` |

`scripts/check_generated.py` fails the build if either drifts from its source;
pre-commit runs it for you.

The brand assets in `custom_components/polestar_data_portal/brand/` are not
generated. They are copied from
[home-assistant/brands](https://github.com/home-assistant/brands/tree/master/custom_integrations/polestar_api),
which is where Home Assistant keeps integration iconography. That directory
holds `icon.png` and `icon@2x.png` only; there is no separate logo, and HACS
requires just the icon.

## Disclaimer

This project is provided **as is, without warranty of any kind**, express or
implied, including but not limited to the warranties of merchantability,
fitness for a particular purpose and non-infringement. In no event shall the
authors or copyright holders be liable for any claim, damages or other
liability arising from, out of, or in connection with the software or its use.
See [LICENSE](LICENSE) for the full terms.

By using this integration you accept that:

- You are responsible for your own use of the Polestar Data Portal, including
  staying within its terms of service and its request limits. Exceeding them
  may get your credential throttled or revoked.
- You are responsible for keeping your own credentials safe.
- Vehicle location and telemetry are personal data. What you do with them once
  they are in Home Assistant &mdash; storing, forwarding, sharing &mdash; is
  your responsibility.
- The maintainers are volunteers. Nothing here is a service, and there is no
  guarantee that it keeps working if Polestar changes the API.

You agree to hold the maintainers harmless from any claim arising out of your
use of this integration or your use of the Polestar Data Portal through it.

**Polestar** is a trademark of Polestar Performance AB. This project is not
affiliated with, authorised by, or connected to Polestar in any way. The icon
shipped in `custom_components/polestar_data_portal/brand/` and shown at the top
of this README is Polestar's mark, taken from the
[Home Assistant brands repository](https://github.com/home-assistant/brands/tree/master/custom_integrations/polestar_api).
It is used only to identify which vehicle this integration talks to, and its
use here implies no endorsement by Polestar.

## Credits

- The [evcc](https://github.com/evcc-io/evcc) project mapped this API for their
  own client first; their work (MIT licensed) was a useful cross-check while
  building this integration. No evcc code is included here.
- [pypolestar](https://github.com/pypolestar/polestar_api) covers Polestar's
  older, unofficial consumer API, which this integration deliberately does not use.

## License

[MIT](LICENSE)
