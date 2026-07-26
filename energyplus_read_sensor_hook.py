"""Minimal EnergyPlus Python API demo.

This script does one thing only:

1. Load the EnergyPlus 26.1 Python API from the installed EnergyPlus folder.
2. Run the model in this workspace through the API, not through EP-Launch.
3. Register one callback that writes a schedule actuator at the start of each
    zone timestep and one callback that reads sensors at the end of each zone
    timestep.
4. Read and print the zone mean air temperature for "Main Zone" and the
    cooling coil electricity rate so the response is visible.

The script is intentionally verbose in its comments because it is meant to be
the first step in learning the EnergyPlus Python API.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# 1) Tell Python where the EnergyPlus installation lives.
#
# EnergyPlus ships the pyenergyplus package inside the installation root,
# so we add that root directory to sys.path before importing the API wrapper.
# On Windows we also add the root to the DLL search path so the EnergyPlus
# runtime library can find its dependent DLLs.
# ---------------------------------------------------------------------------

ENERGYPLUS_ROOT = Path(r"C:\EnergyPlusV26-1-0")
WORKSPACE_ROOT = Path(__file__).resolve().parent
IDF_PATH = WORKSPACE_ROOT / "1ZoneDataCenterCRAC_wApproachTemp.idf"
EPW_PATH = WORKSPACE_ROOT / "USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw"
OUTPUT_DIR = WORKSPACE_ROOT / "sampleSimulation" / "api_demo_output"

if not ENERGYPLUS_ROOT.exists():
    raise SystemExit(f"EnergyPlus install not found: {ENERGYPLUS_ROOT}")

if not IDF_PATH.exists():
    raise SystemExit(f"IDF file not found: {IDF_PATH}")

if not EPW_PATH.exists():
    raise SystemExit(f"Weather file not found: {EPW_PATH}")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Add the install root so `from pyenergyplus.api import EnergyPlusAPI` works.
if str(ENERGYPLUS_ROOT) not in sys.path:
    sys.path.insert(0, str(ENERGYPLUS_ROOT))

from typing import Any

# On Windows, make the EnergyPlus DLLs discoverable during import/runtime.
if os.name == "nt":
    os.add_dll_directory(str(ENERGYPLUS_ROOT))

try:
    from pyenergyplus.api import EnergyPlusAPI  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised when the EnergyPlus API is unavailable
    EnergyPlusAPI = Any  # type: ignore[misc,assignment]


# ---------------------------------------------------------------------------
# 2) Create the API object and the EnergyPlus state.
#
# `EnergyPlusAPI()` exposes three things we need:
# - runtime: register callbacks and run the simulation
# - exchange: request variables, get handles, read values, query simulation time
# - state_manager: create and clean up an EnergyPlus simulation state
# ---------------------------------------------------------------------------

api = EnergyPlusAPI()
state = api.state_manager.new_state()


# We read two output variables:
#   - Zone Mean Air Temperature for the zone named Main Zone.
#   - Cooling Coil Electricity Rate for the main DX cooling coil.
# EnergyPlus treats output variables as sensors that must be requested first.
VARIABLE_NAME = "Zone Mean Air Temperature"
VARIABLE_KEY = "Main Zone"
COIL_ELECTRICITY_NAME = "Cooling Coil Electricity Rate"
COIL_ELECTRICITY_KEY = "Main Cooling Coil 1"

# We write one schedule actuator that is already connected to the thermostat.
# The thermostat in this model uses a dual setpoint object, and this cooling
# schedule feeds that object directly.
ACTUATOR_COMPONENT_TYPE = "Schedule:Compact"
ACTUATOR_CONTROL_TYPE = "Schedule Value"
ACTUATOR_KEY = "Cooling Return Air Setpoint Schedule"

# Alternate the cooling setpoint every hour so the control action is obvious.
COOLING_SETPOINT_LOW_C = 24.0
COOLING_SETPOINT_HIGH_C = 27.0


# We cache the variable handle after the simulation data becomes ready.
# A handle is just EnergyPlus's integer ID for the requested variable.
zone_temperature_handle = -1
cooling_coil_electricity_handle = -1

# We only acquire the actuator handle once, after EnergyPlus says the API data
# layer is fully ready.
cooling_setpoint_handle = -1
handles_initialized = False


def format_simulation_clock(ep_api: EnergyPlusAPI, sim_state) -> str:
    """Build a readable date/time string from EnergyPlus simulation time APIs."""

    # These values come from the currently running EnergyPlus state.
    # They are only meaningful while the simulation is actively running.
    year = ep_api.exchange.year(sim_state)
    month = ep_api.exchange.month(sim_state)
    day = ep_api.exchange.day_of_month(sim_state)

    # current_time is the simulation clock in fractional hours.
    current_time_hours = ep_api.exchange.current_time(sim_state)

    # zone_time_step_num tells us which zone timestep within the current hour
    # EnergyPlus is currently on. This is useful when you are learning how the
    # simulation advances.
    zone_step_number = ep_api.exchange.zone_time_step_number(sim_state)

    return (
        f"{year:04d}-{month:02d}-{day:02d} "
        f"{current_time_hours:.2f} h "
        f"(zone timestep #{zone_step_number})"
    )


def initialize_handles(sim_state) -> None:
    """Get actuator and sensor handles once EnergyPlus has exposed API data."""

    global handles_initialized
    global cooling_setpoint_handle
    global zone_temperature_handle
    global cooling_coil_electricity_handle

    if handles_initialized:
        return

    # EnergyPlus only guarantees handles after the data exchange layer has
    # finished registering the simulation objects.
    if not api.exchange.api_data_fully_ready(sim_state):
        return

    cooling_setpoint_handle = api.exchange.get_actuator_handle(
        sim_state,
        ACTUATOR_COMPONENT_TYPE,
        ACTUATOR_CONTROL_TYPE,
        ACTUATOR_KEY,
    )
    if cooling_setpoint_handle == -1:
        print(
            f"[EnergyPlus] Could not find actuator '{ACTUATOR_COMPONENT_TYPE}' / "
            f"'{ACTUATOR_CONTROL_TYPE}' / '{ACTUATOR_KEY}'."
        )
        handles_initialized = True
        return

    zone_temperature_handle = api.exchange.get_variable_handle(
        sim_state,
        VARIABLE_NAME,
        VARIABLE_KEY,
    )
    if zone_temperature_handle == -1:
        print(
            f"[EnergyPlus] Could not find variable '{VARIABLE_NAME}' for key '{VARIABLE_KEY}'."
        )
        handles_initialized = True
        return

    cooling_coil_electricity_handle = api.exchange.get_variable_handle(
        sim_state,
        COIL_ELECTRICITY_NAME,
        COIL_ELECTRICITY_KEY,
    )
    if cooling_coil_electricity_handle == -1:
        print(
            f"[EnergyPlus] Could not find variable '{COIL_ELECTRICITY_NAME}' for key '{COIL_ELECTRICITY_KEY}'."
        )
        handles_initialized = True
        return

    handles_initialized = True

    print(
        f"[EnergyPlus] Resolved actuator handle for '{ACTUATOR_KEY}' -> "
        f"{cooling_setpoint_handle}"
    )
    print(
        f"[EnergyPlus] Resolved variable handle for '{VARIABLE_KEY}: {VARIABLE_NAME}' -> "
        f"{zone_temperature_handle}"
    )
    print(
        f"[EnergyPlus] Resolved variable handle for '{COIL_ELECTRICITY_KEY}: {COIL_ELECTRICITY_NAME}' -> "
        f"{cooling_coil_electricity_handle}"
    )


def begin_of_zone_timestep_callback(sim_state) -> None:
    """Write the actuator at the start of each zone timestep.

    This is the right place to write a thermostat schedule because the new
    value needs to exist before the zone heat balance and HVAC predictor steps
    use it.
    """

    if api.exchange.warmup_flag(sim_state):
        return

    initialize_handles(sim_state)
    if not handles_initialized or cooling_setpoint_handle == -1:
        return

    hour = api.exchange.hour(sim_state)
    current_time_hours = api.exchange.current_time(sim_state)

    # Alternate the setpoint every hour so you can see the actuator write change
    # in the logs. Even hours use a lower cooling setpoint; odd hours use a
    # higher one.
    setpoint_c = COOLING_SETPOINT_LOW_C if hour % 2 == 0 else COOLING_SETPOINT_HIGH_C

    api.exchange.set_actuator_value(sim_state, cooling_setpoint_handle, setpoint_c)
    written_back = api.exchange.get_actuator_value(sim_state, cooling_setpoint_handle)

    print(
        f"{current_time_hours:.2f} h | Writing {ACTUATOR_KEY} = {setpoint_c:.1f} C "
        f"(readback={written_back:.1f} C)"
    )


def end_of_zone_timestep_callback(sim_state) -> None:
    """Read the live sensor values after EnergyPlus finishes the timestep."""

    initialize_handles(sim_state)

    if api.exchange.warmup_flag(sim_state):
        return

    if not handles_initialized:
        return

    if zone_temperature_handle == -1 or cooling_coil_electricity_handle == -1:
        return

    # Now read the live value for that handle.
    zone_temp_c = api.exchange.get_variable_value(sim_state, zone_temperature_handle)
    coil_electricity_w = api.exchange.get_variable_value(
        sim_state,
        cooling_coil_electricity_handle,
    )

    # Print a compact line each timestep so you can see the value changing.
    print(
        f"{format_simulation_clock(api, sim_state)} | "
        f"{VARIABLE_KEY}: {VARIABLE_NAME} = {zone_temp_c:.3f} C | "
        f"{COIL_ELECTRICITY_KEY}: {COIL_ELECTRICITY_NAME} = {coil_electricity_w:.3f} W"
    )


def main() -> int:
    # Request the variables before the simulation starts. This tells EnergyPlus
    # to make the output variables available during the run.
    api.exchange.request_variable(state, VARIABLE_NAME, VARIABLE_KEY)
    api.exchange.request_variable(state, COIL_ELECTRICITY_NAME, COIL_ELECTRICITY_KEY)

    # Register the write callback at the start of the zone timestep. This is
    # the earliest place we can safely update the thermostat schedule before
    # EnergyPlus uses it for the upcoming calculations.
    api.runtime.callback_begin_zone_timestep_before_init_heat_balance(
        state,
        begin_of_zone_timestep_callback,
    )

    # Register the read callback at the end of the zone timestep so we can see
    # the effect of the actuator after EnergyPlus has completed its calculations
    # and reporting for that timestep.
    api.runtime.callback_end_zone_timestep_after_zone_reporting(
        state,
        end_of_zone_timestep_callback,
    )

    # Optional: mute EnergyPlus console chatter so the sensor prints are easy
    # to see. The .err file and exit code still report problems.
    api.runtime.set_console_output_status(state, False)

    # Build the same command line EnergyPlus would receive from the executable.
    # `run_energyplus` expects the arguments only, not the program name.
    command_line_args = [
        "-d",
        str(OUTPUT_DIR),
        "-w",
        str(EPW_PATH),
        str(IDF_PATH),
    ]

    print("[EnergyPlus] Starting simulation...")
    print(f"[EnergyPlus] IDF: {IDF_PATH}")
    print(f"[EnergyPlus] EPW: {EPW_PATH}")
    print(f"[EnergyPlus] Output directory: {OUTPUT_DIR}")
    print()

    try:
        exit_code = api.runtime.run_energyplus(state, command_line_args)
        print()
        print(f"[EnergyPlus] Simulation finished with exit code {exit_code}")
        return exit_code
    finally:
        # Always release the EnergyPlus state when you are done.
        api.state_manager.delete_state(state)


if __name__ == "__main__":
    raise SystemExit(main())