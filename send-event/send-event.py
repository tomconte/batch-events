#!/usr/local/bin/python

# Send notification to Event Grid

import json
import os
import subprocess
import uuid
from datetime import datetime

endpoint = os.environ['GRID_ENDPOINT']
key = os.environ['GRID_KEY']

job_id = os.environ['AZ_BATCH_JOB_ID']

event = [{
    'id': str(uuid.uuid4()),
    'eventType': 'jobFinished',
    'subject': job_id,
    'eventTime': datetime.strftime(datetime.now(), '%Y-%m-%dT%H:%M:%S.%fZ'),
    'data': {
        'foo': 'bar'
    }
}]

subprocess.run(
    args=[
        'curl',
        '--silent',
        '-H', 'aeg-sas-key:' + key,
        '-d', json.dumps(event),
        endpoint
    ]
)
