# Camper API

The goal is to run this service on a raspberry pi zero 2 w to collect data. The project is inspired by home-assistant. I would like to keep to project as compact as possible.

## Development

Status:
- [x] Stage 1: Victron BLE devices
- [x] Stage 2: Control and measure camper basics
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
* Read and store car starter battery voltage

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

Dummy serial port:
* `socat -d -d pty,raw,echo=0 pty,raw,echo=0`

remote:
* local port to tcp/ip: `socat /dev/serial0,raw,echo=0,b19200 tcp-listen:2323,reuseaddr`
* connect to this port remote: `socat -d -d /dev/ttyUSB1,raw,echo=0,b57600 tcp:xx.local:2323`

## Database migration

create: `alembic revision --autogenerate -m "message"`
update: `alembic upgrade head`