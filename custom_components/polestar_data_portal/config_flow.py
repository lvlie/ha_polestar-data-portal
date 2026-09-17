"""Config flow for the Polestar Data Portal integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import PolestarApiError, PolestarAuthError, PolestarDataPortalApi
from .const import (
    CONF_ACCOUNT_ID,
    CONF_DELEGATED_ACCOUNT_ID,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_TOKEN_URL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_TOKEN_URL,
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)

# Shown in the form description so users land on the account picker rather
# than a market-specific URL that may not exist for them.
PORTAL_URL = "https://data-portal.polestar.com"


def _credentials_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """Build the credential form, pre-filled from ``defaults`` when re-authing."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_CLIENT_ID, default=defaults.get(CONF_CLIENT_ID, vol.UNDEFINED)
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Required(CONF_CLIENT_SECRET): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required(
                CONF_ACCOUNT_ID,
                default=defaults.get(CONF_ACCOUNT_ID, vol.UNDEFINED),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Required(
                CONF_TOKEN_URL,
                default=defaults.get(CONF_TOKEN_URL, DEFAULT_TOKEN_URL),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
            vol.Optional(
                CONF_DELEGATED_ACCOUNT_ID,
                description={
                    "suggested_value": defaults.get(CONF_DELEGATED_ACCOUNT_ID)
                },
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
        }
    )


async def _async_validate(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> tuple[list[str], dict[str, str]]:
    """Check the credentials by requesting a token and listing vehicles."""
    errors: dict[str, str] = {}

    try:
        api = PolestarDataPortalApi(
            async_get_clientsession(hass),
            client_id=user_input[CONF_CLIENT_ID],
            client_secret=user_input[CONF_CLIENT_SECRET],
            account_id=user_input[CONF_ACCOUNT_ID],
            token_url=user_input[CONF_TOKEN_URL],
            delegated_account_id=user_input.get(CONF_DELEGATED_ACCOUNT_ID),
        )
    except ValueError as err:
        reason = "insecure_token_url" if "https" in str(err) else "invalid_token_url"
        return [], {CONF_TOKEN_URL: reason}

    try:
        vins = await api.async_get_vehicles()
    except PolestarAuthError as err:
        _LOGGER.debug("Credential validation failed: %s", err)
        errors["base"] = "invalid_auth"
    except PolestarApiError as err:
        _LOGGER.debug("Could not reach the Data Portal: %s", err)
        errors["base"] = "cannot_connect"
    else:
        if not vins:
            errors["base"] = "no_vehicles"
        return vins, errors

    return [], errors


class PolestarDataPortalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Polestar Data Portal config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the Data Portal credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = _clean(user_input)
            vins, errors = await _async_validate(self.hass, user_input)

            if not errors:
                # The account ID identifies the Data Portal account these
                # credentials belong to, so it keeps the entry unique even if
                # the client ID is rotated later.
                await self.async_set_unique_id(user_input[CONF_ACCOUNT_ID])
                self._abort_if_unique_id_configured()

                _LOGGER.debug("Data Portal credentials cover %d vehicle(s)", len(vins))
                return self.async_create_entry(
                    title="Polestar Data Portal",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_credentials_schema(user_input),
            errors=errors,
            description_placeholders={"portal_url": PORTAL_URL},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after the credentials stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect replacement credentials for an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            user_input = _clean(user_input)
            _, errors = await _async_validate(self.hass, user_input)

            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_credentials_schema(user_input or entry.data),
            errors=errors,
            description_placeholders={"portal_url": PORTAL_URL},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> PolestarDataPortalOptionsFlow:
        """Return the options flow."""
        return PolestarDataPortalOptionsFlow()


class PolestarDataPortalOptionsFlow(OptionsFlow):
    """Handle the polling interval option."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL_MINUTES: int(
                        user_input[CONF_SCAN_INTERVAL_MINUTES]
                    )
                }
            )

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL_MINUTES, default=current
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_MINUTES,
                            max=MAX_SCAN_INTERVAL_MINUTES,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    """Trim whitespace pasted in from the Data Portal and drop empty values."""
    cleaned = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in user_input.items()
    }
    return {key: value for key, value in cleaned.items() if value not in ("", None)}
