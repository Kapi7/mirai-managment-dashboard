#!/bin/bash
# Start Emma Service

cd "$(dirname "$0")"

# Install dependencies
pip install -r requirements.txt

# Start the service
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-5002}
