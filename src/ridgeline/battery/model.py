"""Battery physics shared by every dispatch method.

Round-trip efficiency is split evenly between charging and discharging:
eta_c = eta_d = sqrt(RTE). Charging `c` kW for `dt` hours stores `eta_c * c * dt` kWh;
discharging `d` kW for `dt` hours delivers `d * dt` kWh to the site and removes
`d * dt / eta_d` kWh from storage. Usable energy is bounded by [soc_min, soc_max] x capacity.

Degradation is not modeled within a year; M4 applies it as a per-year capacity derate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ridgeline.data.schemas import BatterySpec


@dataclass(frozen=True)
class BatteryLimits:
    power_kw: float
    e_min_kwh: float
    e_max_kwh: float
    eta_charge: float
    eta_discharge: float


def battery_limits(spec: BatterySpec) -> BatteryLimits:
    eta = math.sqrt(spec.round_trip_efficiency)
    return BatteryLimits(
        power_kw=spec.power_kw,
        e_min_kwh=spec.soc_min * spec.energy_kwh,
        e_max_kwh=spec.soc_max * spec.energy_kwh,
        eta_charge=eta,
        eta_discharge=eta,
    )
