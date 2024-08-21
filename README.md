# Tools

## Environment setup & run

Walk through following steps:
* Run from `camper-api` subdirectory: `python3 -m venv ./venv`
* Activate venv: `source ./venv/bin/activate`
* Install dependancies: `pip install -r requirements.txt`
* Setup/upgrade the database: `alembic upgrade head`

You can now run the API using: `uvicorn camper_api.main:app --reload` from the venv.

## Database migration

`alembic revision -m "create account table"`
