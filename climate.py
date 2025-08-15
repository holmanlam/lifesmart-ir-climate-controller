"""Support for LifeSmart IR Climate via remote control."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_WHOLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LifeSmartDevice, generate_entity_id
from .const import (
    DEVICE_ID_KEY,
    DEVICE_NAME_KEY,
    DEVICE_TYPE_KEY,
    DOMAIN,
    GENERIC_CONTROLLER_TYPES,
    HUB_ID_KEY,
    MANUFACTURER,
)

_LOGGER = logging.getLogger(__name__)
# 確保初始化時輸出一條明顯的日誌
_LOGGER.error("========== LifeSmart IR Climate module loaded ==========")

# 空調模式對應
HVAC_MODES = {
    HVACMode.AUTO: 0,
    HVACMode.COOL: 1,
    HVACMode.DRY: 2,
    HVACMode.FAN_ONLY: 3,
    HVACMode.HEAT: 4,
    HVACMode.OFF: 5,
}

# 風速設置
FAN_MODES = {
    FAN_AUTO: 0,
    FAN_LOW: 1,
    FAN_MEDIUM: 2,
    FAN_HIGH: 3,
}

# 預設溫度範圍
MIN_TEMP = 16
MAX_TEMP = 30


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities: AddEntitiesCallback = None):
    """Set up the LifeSmart IR climate entities."""
    _LOGGER.error("========== LifeSmart IR Climate setup_entry called ==========")
    
    # 允許直接從 __init__.py 調用，這種情況下 async_add_entities 可能是空列表或 None
    if async_add_entities is None or not callable(async_add_entities):
        _LOGGER.warning("async_add_entities is not callable, creating a climate list only")
        async_add_entities = lambda devices: _LOGGER.info("Would add %d climate devices if properly called", len(devices))
    
    devices = hass.data[DOMAIN][config_entry.entry_id]["devices"]
    exclude_devices = hass.data[DOMAIN][config_entry.entry_id]["exclude_devices"]
    exclude_hubs = hass.data[DOMAIN][config_entry.entry_id]["exclude_hubs"]
    client = hass.data[DOMAIN][config_entry.entry_id]["client"]
    climate_devices = []
    
    # 記錄所有設備類型以便診斷
    device_types = set([device[DEVICE_TYPE_KEY] for device in devices])
    _LOGGER.error("Found device types: %s", device_types)
    
    for device in devices:
        device_id = device[DEVICE_ID_KEY]
        hub_id = device[HUB_ID_KEY]
        device_type = device[DEVICE_TYPE_KEY]
        
        _LOGGER.debug(
            "Processing device for IR climate - ID: %s, Hub: %s, Type: %s", 
            device_id, hub_id, device_type
        )
        
        if device_id in exclude_devices or hub_id in exclude_hubs:
            _LOGGER.debug("Skipping excluded device: %s", device_id)
            continue

        if device_type != "SL_P_IR":
            _LOGGER.debug("Skipping non-IR controller device: %s", device_type)
            continue
            
        _LOGGER.error(
            "Found LifeSmart IR Controller for climate - ID: %s, Hub: %s, Name: %s", 
            device_id, hub_id, device[DEVICE_NAME_KEY]
        )
            
        try:
            ha_device = LifeSmartDevice(
                device,
                client,
            )
            
            # 檢查是否有可用的遙控器列表
            try:
                remote_list = await client.get_ir_remote_list_async(hub_id)
                _LOGGER.error("Remote list for climate (raw): %s", remote_list)
                
                if remote_list:
                    # 輸出完整的遙控器列表以便診斷
                    _LOGGER.error("Found %d remote controls for device %s", len(remote_list), device_id)
                    for i, remote in enumerate(remote_list):
                        _LOGGER.error("Remote #%d: %s", i+1, remote)
                    
                    # 尋找空調遙控器（category 為 ac 的遙控器）
                    ac_remotes_found = 0
                    
                    for remote_id, remote_data in remote_list.items():
                        _LOGGER.error("Checking remote ID %s: %s", remote_id, remote_data)
                        if isinstance(remote_data, dict) and remote_data.get("category") == "ac":
                            _LOGGER.error("Found AC remote for climate: %s", remote_data)
                            climate_device = LifeSmartIRClimate(
                                ha_device,
                                device,
                                client,
                                remote_data,
                                remote_id
                            )
                            climate_devices.append(climate_device)
                            ac_remotes_found += 1

                    
                    if ac_remotes_found == 0:
                        _LOGGER.warning("No AC remotes found for device %s", device_id)
                else:
                    _LOGGER.warning("No remote controls found for device %s", device_id)
            except Exception as ex:
                _LOGGER.error("Failed to load remote list for climate: %s", ex, exc_info=True)
        except Exception as ex:
            _LOGGER.error("Failed to process device: %s", ex, exc_info=True)
    
    if not climate_devices:
        _LOGGER.warning("No LifeSmart IR Climate Controllers configured")
    else:
        _LOGGER.info("Found %d LifeSmart IR Climate Controllers", len(climate_devices))
            
    async_add_entities(climate_devices)


class LifeSmartIRClimate(ClimateEntity):
    """LifeSmart IR Climate Device."""

    def __init__(self, device, raw_device_data, client, remote_data, ai) -> None:
        """Initialize the climate device."""
        self._device = device
        self._client = client
        self._raw_device_data = raw_device_data
        self._remote_data = remote_data
        
        # 設備基本信息
        self._name = f"{raw_device_data[DEVICE_NAME_KEY]} {remote_data.get('name', 'AC')}"
        self._hub_id = raw_device_data[HUB_ID_KEY]
        self._device_id = raw_device_data[DEVICE_ID_KEY]
        self._device_type = raw_device_data[DEVICE_TYPE_KEY]
        
        # 遙控器信息
        self._ai = ai
        
        self._category = remote_data.get("category", "ac")
        self._brand = remote_data.get("brand", "")
        
        # 生成 entity_id
        self.entity_id = f"climate.ir_{self._device_type.lower()}_{self._hub_id.lower()}_{self._device_id.lower()}"
        
        # 空調狀態
        self._hvac_mode = HVACMode.OFF
        self._target_temperature = 25
        self._fan_mode = FAN_AUTO
        self._swing_mode = False
        self._attr_is_on = False
        
        # 支持的功能
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.FAN_MODE
        )
        
        # 溫度範圍
        self._attr_min_temp = MIN_TEMP
        self._attr_max_temp = MAX_TEMP
        self._attr_target_temperature_step = 1
        
        _LOGGER.error(
            "Initialized LifeSmart IR Climate: %s (AI: %s, Brand: %s)", 
            self._name, self._ai, self._brand
        )

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self._device_id}_{self._ai}_climate"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._hub_id, self._device_id)},
            name=self._raw_device_data[DEVICE_NAME_KEY],
            manufacturer=MANUFACTURER,
            model=self._device_type,
            sw_version=self._raw_device_data["ver"],
            via_device=(DOMAIN, self._hub_id),
        )

    @property
    def current_temperature(self):
        """Return the current temperature."""
        # IR 控制器無法獲取實際溫度
        return None

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def target_temperature(self):
        """Return the target temperature."""
        return self._target_temperature

    @property
    def precision(self):
        """Return the precision of the system."""
        return PRECISION_WHOLE

    @property
    def hvac_mode(self):
        """Return hvac operation mode."""
        return self._hvac_mode

    @property
    def hvac_modes(self):
        """Return the list of available hvac operation modes."""
        return list(HVAC_MODES.keys())

    @property
    def fan_mode(self):
        """Return the fan setting."""
        return self._fan_mode

    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        return list(FAN_MODES.keys())

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        _LOGGER.info("Setting HVAC mode to %s", hvac_mode)
        
        if hvac_mode == HVACMode.OFF:
            # 關閉空調
            self._attr_is_on = False
            self._hvac_mode = HVACMode.OFF
            cmd = await self._send_ac_command(0)  # 0 means power off
            if cmd:
                self.async_write_ha_state()
        else:
            # 設置模式並打開空調
            self._hvac_mode = hvac_mode
            self._attr_is_on = True
            cmd = await self._send_ac_command(1)  # 1 means power on
            if cmd:
                self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        if ATTR_TEMPERATURE in kwargs:
            self._target_temperature = int(kwargs[ATTR_TEMPERATURE])
            _LOGGER.info("Setting temperature to %s", self._target_temperature)
            
            if self._hvac_mode != HVACMode.OFF:
                cmd = await self._send_ac_command(1)  # 1 means power on
                if cmd:
                    self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        _LOGGER.info("Setting fan mode to %s", fan_mode)
        self._fan_mode = fan_mode
        
        if self._hvac_mode != HVACMode.OFF:
            cmd = await self._send_ac_command(1)  # 1 means power on
            if cmd:
                self.async_write_ha_state()

    async def async_turn_on(self):
        """Turn on."""
        _LOGGER.info("Turning on AC")
        if self._hvac_mode == HVACMode.OFF:
            # 預設模式為製冷
            self._hvac_mode = HVACMode.COOL
        
        self._attr_is_on = True
        cmd = await self._send_ac_command(1)  # 1 means power on
        if cmd:
            self.async_write_ha_state()

    async def async_turn_off(self):
        """Turn off."""
        _LOGGER.info("Turning off AC")
        self._attr_is_on = False
        self._hvac_mode = HVACMode.OFF
        cmd = await self._send_ac_command(0)  # 0 means power off
        if cmd:
            self.async_write_ha_state()

    async def _send_ac_command(self, power):
        """Send IR command to the AC."""
        try:
            # 設置電源狀態
            power_state = power
            
            # 設置模式
            mode_value = HVAC_MODES.get(self._hvac_mode, 0)
            if self._hvac_mode == HVACMode.OFF:
                mode_value = 1  # 默認使用製冷模式，但將電源設為關
                
            # 設置風速
            fan_value = FAN_MODES.get(self._fan_mode, 0)
            
            # 檢查 ai 是否存在
            if not self._ai:
                _LOGGER.error("Missing AI (remote ID) for climate command")
                return False
                
            # 詳細記錄所有參數
            _LOGGER.error(
                "Sending AC command - Hub: %s, AI: %s, Device: %s, Category: %s, Brand: %s",
                self._hub_id, self._ai, self._device_id, self._category, self._brand
            )
            
            # 發送命令
            _LOGGER.error(
                "Command parameters - Power: %d, Mode: %d, Temp: %d, Fan: %d",
                power_state, mode_value, self._target_temperature, fan_value
            )
            
            result = await self._client.send_ir_ackey_async(
                self._hub_id,
                self._ai,
                self._device_id,
                self._category,
                self._brand,
                "power",
                power_state,
                mode_value,
                self._target_temperature,
                fan_value,
                0  # 擺動設為0
            )
            
            _LOGGER.error("AC command result: %s", result)
            return result
        except Exception as ex:
            _LOGGER.error("Error sending AC command: %s", ex, exc_info=True)
            return None 