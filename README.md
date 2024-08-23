# Camper API

The goal is to run this service on a raspberry pi zero 2 w to collect data. The project is inspired by home-assistant. I would like to keep to project as compact as possible.

## Development

Status:
- [x] Stage 1: Victron BLE devices
- [ ] Stage 2: Control and measure camper basics
- [ ] Stage 3: Statistics

### Stage 1: Victron BLE devices

Collect state data from victron BLE devices periodically and store it to a SQLite database. State data is removed after 10 days.

The following information is stored and controllable through the API:
* Sensor: The sensors to collect data from with address and key
* Entity: Entities of a sensor the collect and store data from
* State: Sample from entity on moment

Inspired from https://data.home-assistant.io/docs/states

### Stage 2: Control and measure camper basics

For example:
* Read and store fresh and dirty water tank status
* Control household power and water pump power
* Read and store household power, water pump power and exteral power connected status
* Read and store car battery voltage

### Stage 3: Statistics

Add Long- and short-term statistics in the same way as home-assistant with:
- 5 min and hourly stats. Where 5 min stats are removed after 10 days and hourly is kept indefinitely 
- Support several entity_types:
 - `measurement`: Keep track of mean, min and max
 - `total` and `total_increasing`: Integrated over time; Track `last_reset`, `state`, `sum`, `sum_increase` and `sum_decrease` (only for `total`)
- Implement API calls to retrieve, configure and fix.

For details on https://developers.home-assistant.io/docs/core/entity/sensor

## Environment setup & run

Walk through following steps:
* Run from `camper-api` subdirectory: `python3 -m venv ./venv`
* Activate venv: `source ./venv/bin/activate`
* Install dependancies: `pip install -r requirements.txt`
* Setup/upgrade the database: `alembic upgrade head`

You can now run the API using: `uvicorn camper_api.main:app --reload` from the venv.

Run at boot:
* sudo cp camper_api.service /etc/systemd/system
* sudo systemctl deamon-reload
* sudo systemctl enable camper_api.service

service checks:
* sudo systemctl status camper_api.service
* journalctl -u camper_api.service -f

### Add some data

sensors:
id: 1
{
    "address": "FB:A2:B2:2E:12:55",
    "key": "c10a7be1241dd928a17a0bc61eec8f50",
    "name": "SmartShunt"
}
id: 2
{
    "address": "CF:3B:A3:E5:58:79",
    "key": "c35bc9a772f02d904010bf8cd4bab7cf",
    "name": "SmartSolar"
}

entities:
sensor_id: 1
{
    "name": "rssi",
    "unit": "dBm",
    "description": "Bluetooth signal strength"
}
{
    "name": "aux_mode"
}
{
    "name": "voltage"
}
{
    "name": "current"
}
{
    "name": "remaining_mins"
}
{
    "name": "soc"
}
{
    "name": "consumed_ah",
    "unit": "Ah",
    "description": "Consumed energy"
}

sensor_id: 2
{
    "name": "rssi",
    "unit": "dBm",
    "description": "Bluetooth signal strength"
}
{
    "name": "battery_charging_current"
}
{
    "name": "battery_voltage"
}
{
    "name": "charge_state"
}
{
    "name": "external_device_load"
}
{
    "name": "solar_power"
}
{
    "name": "yield_today"
}

## Database migration

`alembic revision -m "create account table"`