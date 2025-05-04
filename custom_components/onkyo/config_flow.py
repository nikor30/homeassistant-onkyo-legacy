"""Config flow for Onkyo integration (stub to prevent loading errors)."""

from homeassistant import config_entries
from .const import DOMAIN  # Ensure DOMAIN is defined in const.py or __init__.py

class OnkyoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Onkyo integration."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Abort config flow as UI config is not supported."""
        return self.async_abort(reason="no_config_flow")
