#!/usr/bin/env python

import json
import os
import shlex
import sys
import uuid

import azure.batch._batch_service_client as batch
import azure.batch.batch_auth as batch_auth
import azure.batch.models as batchmodels

if len(sys.argv) != 5:
    print("Usage: %s <pool-name> <registry-address> <event-grid-endpoint> <event-grid-key>", sys.argv[0])
    exit(1)

registry = sys.argv[2]

# Connect to the Batch account

credentials = batch_auth.SharedKeyCredentials(os.environ['BATCH_ACCOUNT_NAME'], os.environ['BATCH_ACCOUNT_KEY'])

batch_client = batch.BatchServiceClient(credentials, batch_url=os.environ['BATCH_ACCOUNT_URL'])

# Create the job

job_name = "test-container-job-"+str(uuid.uuid4())

job = batch.models.JobAddParameter(
    id = job_name,
    pool_info = batch.models.PoolInformation(pool_id=sys.argv[1]),
    uses_task_dependencies = True
)

batch_client.job.add(job)

# Add main task

task_container_settings = batchmodels.TaskContainerSettings(
    image_name = registry + "/progrium-stress"
)

main_task_id = "test-container-task-"+str(uuid.uuid4())

main_task = batch.models.TaskAddParameter(
    id = main_task_id,
    command_line = "--cpu 2 --timeout 60s",
    container_settings = task_container_settings
)

batch_client.task.add(job_id=job_name, task=main_task)

# Add event notification task

notification_task_container_settings = batchmodels.TaskContainerSettings(
    image_name = registry + "/send-event"
)

notification_task = batch.models.TaskAddParameter(
    id = "test-notification-task-"+str(uuid.uuid4()),
    # Set up the dependency to the main task
    depends_on = batch.models.TaskDependencies(
        task_ids = [main_task_id]
    ),
    environment_settings=[
      batch.models.EnvironmentSetting(name="GRID_ENDPOINT", value=sys.argv[3]),
      batch.models.EnvironmentSetting(name="GRID_KEY", value=sys.argv[4]),
    ],
    command_line = '/app/send-event.py',
    container_settings = notification_task_container_settings
)

batch_client.task.add(job_id=job_name, task=notification_task)

# Print job information

print(job.serialize())
