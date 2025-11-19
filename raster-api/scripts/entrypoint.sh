#!/bin/bash
# wait for the database
/usr/local/bin/wait-for-it.sh -t 120 -h $POSTGRES_HOST -p $POSTGRES_PORT -- echo "Database is ready"
#
# execute the command passed to the docker service
exec uvicorn titiler.application.main:app --host ${HOST} --port 8080