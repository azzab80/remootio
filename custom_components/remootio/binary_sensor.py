"""Support for Remootio doorbell binary sensor."""
from __future__ import annotations

import asyncio
import logging

from aioremootio import Event, EventType, Listener, RemootioClient

from homeassistant.components import cover
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTR_SERIAL_NUMBER, CONF_SERIAL_NUMBER, DOMAIN, REMOOTIO_CLIENT

_LOGGER = logging.getLogger(__name__)

DOORBELL_RESET_SECONDS = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a ``RemootioDoorbellBinarySensor`` entity based on the given configuration entry."""

    serial_number: str = config_entry.data[CONF_SERIAL_NUMBER]
    remootio_client: RemootioClient = hass.data[DOMAIN][config_entry.entry_id][
        REMOOTIO_CLIENT
    ]

    async_add_entities(
        [RemootioDoorbellBinarySensor(serial_number, config_entry.title, remootio_client)]
    )


class RemootioDoorbellBinarySensor(BinarySensorEntity):
    """Binary sensor entity representing the Remootio doorbell input."""

    _attr_device_class = BinarySensorDeviceClass.SOUND
    _attr_has_entity_name = True
    _attr_name = "Doorbell"
    _attr_should_poll = False

    def __init__(
        self,
        serial_number: str,
        name: str,
        remootio_client: RemootioClient,
    ) -> None:
        """Initialize this binary sensor entity."""
        super().__init__()
        self._serial_number = serial_number
        self._attr_unique_id = f"{serial_number}_doorbell"
        self._attr_is_on = False
        self._remootio_client = remootio_client
        self._reset_task: asyncio.Task | None = None
        # Use the same device identifiers as the cover entity so both appear on one device card.
        self._attr_device_info = DeviceInfo(
            identifiers={(cover.DOMAIN, serial_number)},
        )

    async def async_added_to_hass(self) -> None:
        """Register event listener to be notified of doorbell presses."""
        await self._remootio_client.add_event_listener(
            RemootioDoorbellEventListener(self)
        )

    async def async_doorbell_pressed(self) -> None:
        """Handle a doorbell press: turn on briefly, then reset."""
        self._attr_is_on = True
        self.async_write_ha_state()

        self.hass.bus.async_fire(
            f"{DOMAIN}_doorbell_pushed",
            {
                ATTR_ENTITY_ID: self.entity_id,
                ATTR_SERIAL_NUMBER: self._serial_number,
                ATTR_NAME: self.name,
            },
        )

        if self._reset_task is not None:
            self._reset_task.cancel()

        self._reset_task = self.hass.async_create_task(self._reset_after_delay())

    async def _reset_after_delay(self) -> None:
        """Reset the doorbell sensor to off after a short delay."""
        await asyncio.sleep(DOORBELL_RESET_SECONDS)
        self._attr_is_on = False
        self.async_write_ha_state()
        self._reset_task = None


class RemootioDoorbellEventListener(Listener[Event]):
    """Listener invoked when the Remootio device sends a DoorbellPushed event."""

    _owner: RemootioDoorbellBinarySensor

    def __init__(self, owner: RemootioDoorbellBinarySensor) -> None:
        """Initialize an instance of this class."""
        super().__init__()
        self._owner = owner

    async def execute(self, client: RemootioClient, subject: Event) -> None:
        """Execute this listener. Trigger the doorbell sensor on DoorbellPushed events."""
        if subject.type == EventType.DOORBELL_PUSHED:
            _LOGGER.debug(
                "Doorbell pushed. RemootioBinarySensorEntityId [%s] RemootioBinarySensorUniqueId [%s]",
                self._owner.entity_id,
                self._owner.unique_id,
            )
            await self._owner.async_doorbell_pressed()
