# Batch job notifications using Event Grid and Functions

This sample shows how to send events from Azure Batch, such as end-of-job notifications, using task dependencies, Azure Event Grid, and Azure Functions. At a high level, we are going to use a custom Event Grid topic to send an event from a "notification" task within a Batch job. This event will be received by an Azure Function, using an Event Grid trigger.

## Create the Function host and Event Grid topic/subscription

From a shell session, define some variables that will be used during the deployment:

```
RESOURCE_GROUP=batch-events
FUNCTION_APP=batch-grid-event
```

### Deploy the Function host

Deploy the provided ARM template `arm-function-app.json` to create an App Service Plan and a Function host. This will be used to host our Function application. You can inspect the template to see additional parameters you could use, like the App Service SKU or the details of the Function Web App configuration. Since we are planning to deploy a Python function, we are requesting a Linux environment and a Docker image that provides the required runtime environment (currently Python 3.6).

```
az group create --name ${RESOURCE_GROUP} --location southcentralus
az group deployment create --resource-group ${RESOURCE_GROUP} \
  --template-file arm-function-app.json \
  --parameters appName=${FUNCTION_APP}
```

### Deploy the Function app

Deploy the pre-baked Function project located in `batch-event-fn`. This is a simple implementation of an Event Grid trigger in Python, that will print the event properties in a log file.

```
cd batch-event-fn
func azure functionapp publish ${FUNCTION_APP}
cd ..
```

Alternatively, if you want to create a new Function app from scratch, you could use the following commands:

```
func init --worker-runtime python
func new --language python --name job-event --template "Azure Event Grid trigger"
```

You can then deploy this new app using the `publish` command above.

### Retrieve the key to the Event Grid trigger function

Retrieve the Resource ID of the Function host that you deployed above. This ID uniquely identifies your App Service within Azure's Resource Manager.

```
RESOURCE_ID=$(az functionapp show --resource-group ${RESOURCE_GROUP} --name ${FUNCTION_APP} --output tsv --query id)
```

Using this Resource ID, retrieve the system key for the Event Grid trigger function. We will use this key to authenticate the callbacks from Event Grid.

```
FUNCTION_KEY=$(az rest --method post --uri "${RESOURCE_ID}/host/default/listKeys?api-version=2018-11-01" --output tsv --query systemKeys.eventgrid_extension)
```

You can now assemble the URL that can be used to subscribe to Event Grid events.

```
WEBHOOK_URL="https://${FUNCTION_APP}.azurewebsites.net/runtime/webhooks/eventgrid?functionName=job-event&code=${FUNCTION_KEY}"
```

### Create the Event Grid topic and subscription

Use the second provided ARM template to create a custom topic and subscribe the Function to the events from this topic. The callback URL is passed as a parameter.

```
az group deployment create --resource-group ${RESOURCE_GROUP} \
  --template-file arm-event-grid-topic-sub.json \
  --parameters eventGridTopicName=job-event \
  eventGridSubscriptionName=job-event-sub \
  eventGridSubscriptionUrl=${WEBHOOK_URL}
```

## Post an event to the custom topic

Now that we have created a topic and that a Function is listening for events, we can test event delivery using a simple cURL command.

To do this, we will need to retrieve the URL and the key of the custom topic endpoint. You will also use these values later when setting up the notification from an Azure Batch task.

```
ENDPOINT=$(az eventgrid topic show --name job-event -g ${RESOURCE_GROUP} --output tsv --query "endpoint")
KEY=$(az eventgrid topic key list --name job-event -g ${RESOURCE_GROUP} --output tsv --query "key1")
```

In another terminal window, you can stream the logs from the Event Grid Function (you can also use the Azure Portal).

```
func azure functionapp logstream $FUNCTION_APP
```

Assemble a minimal test payload:

```
data='[{"id":"foo","subject":"bar","eventType":"test","eventTime":"2017-06-26T18:41:00.9584103Z","dataVersion":"1.0"}]'
```

And send the event:

```
curl -X POST -H "aeg-sas-key:$KEY" -d $data "$ENDPOINT"
```

You should see in the Function log stream that the event was received.

## Create a Batch task to trigger the event

You can now send an event from any Batch task just by using cURL as shown above, or any other means to send an HTTP request. If you do not want to send the event from your actual compute task, you can schedule a specific event-sending task within a job, using [task dependencies](https://docs.microsoft.com/en-us/azure/batch/batch-task-dependencies). This "notification" task can be configured to run once all the other tasks in the job are finished (successfully or not).

In this example we are using a container-enabled Batch pool, which means that each task can run in a Docker-compatible container. We are going to use a small dedicated Docker image to schedule a notification task within a job.

### Build & push the Docker image

The `send-event` folder contains a Docker file and a simple Python script invoking `curl` to send an event. The Event Grid endpoint and key are passed to the Python script using environment variables. The image uses the Alpine variant of the Python base image to keep it as small as possible. The script also shows the usage of some [Batch environment variables](https://docs.microsoft.com/en-us/azure/batch/batch-compute-node-environment-variables) that can be used to introspect the environment, e.g. find the ID of the current job.

Build the image:

```
cd send-event
docker build -t send-event .
cd ..
```

You can try the image right away, using the Event Grid endpoint/key variables from above. We are also faking the `AZ_BATCH_JOB_ID` environment variable, which will be set in the Batch runtime environment.

```
docker run --rm -it -e GRID_ENDPOINT=${ENDPOINT} -e GRID_KEY=${KEY} -e AZ_BATCH_JOB_ID=foo send-event /app/send-event.py
```

In order to use the image from a Batch task, you will need to tag and push it to an Docker registry. For more information on how to use containers in Batch, please see the documentation for [Batch container workloads](https://docs.microsoft.com/en-us/azure/batch/batch-docker-container-workloads). To push the image to an [Azure Container Registry](https://docs.microsoft.com/en-us/azure/container-registry/container-registry-intro), the commands will look like this:

```
REGISTRY=myregistry
az acr login --name ${REGISTRY}
docker tag send-event ${REGISTRY}.azurecr.io/send-event
docker push ${REGISTRY}.azurecr.io/send-event
```

### Use the image in a Batch container job

Next we are going to create a job consisting of two tasks: one "main" tasks which does some real work, and a second task that depends on the first and uses our `send-event` container image to send an end-of-job event. For our main task we will use a simple benchmarking container image called `progrium/stress`, which you should pull and push to your private container registry:

```
docker pull progrium/stress
docker tag progrium/stress ${REGISTRY}.azurecr.io/progrium-stress
docker push ${REGISTRY}.azurecr.io/progrium-stress
```

We are now ready to use our event-sending image from a task within a Batch job. Let's first install the Python SDK for Batch:

```
cd batch-scripts
pip install -r requirements.txt
```

In order to authenticate to the Azure Batch service, you will need to retrieve the account name, account key, and account URL from your deployment. In the Web UI, you will find this information in the Keys section of the Batch Account.

```
export BATCH_ACCOUNT_NAME=foo
export BATCH_ACCOUNT_KEY=bar
export BATCH_ACCOUNT_URL=https://foobar.southcentralus.batch.azure.com
```

Now you can launch the `run_batch_task.py` script to create a new job with two tasks. You will need pass the name of the container-enabled pool you want to use, the address of your Docker registry, plus the endpoint and key variables for Event Grid. You can inspect the source code to see how the tasks are created, and how the dependencies are set up.

```
./run_batch_task.py container-pool ${REGISTRY}.azurecr.io $ENDPOINT $KEY
```

The script will output the ID of the job created. You can use the Azure Batch UI to monitor the progress. Once the job is finished, you should see the event received in your Function log.

## Clean up

Remove all the resources created in this documentation:

```
az group delete --name ${RESOURCE_GROUP}
```
