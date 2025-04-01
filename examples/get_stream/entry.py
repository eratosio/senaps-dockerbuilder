import subprocess
import logging
import json
import sys
from as_models.models import model


def list_packages():
    result = subprocess.run(["pip", "list"], stdout=subprocess.PIPE)
    print(result.stdout.decode("utf-8"))


@model("eratos.test.model")
def entry(context):
    # print environment
    print("Testing context updater")
    try:
        context.update("blah blah blah")
    except:
        print("Updater did not work")
    with open("manifest.json", "r") as f:
        manifest = json.load(f)
        base_image = manifest["baseImage"]
    print(f"Testing base image {base_image}")
    print(f"Running on Python version {sys.version}")
    print("Python packages installed:")
    print("blah blah")
    list_packages()

    # check senaps logging working correctly
    logger = logging.getLogger()
    logger.debug("THIS IS A TEST DEBUG MESSAGE")
    logger.info("THIS IS A TEST MESSAGE")
    logger.warning("THIS IS A TEST WARNING")
    logger.error("THIS IS A TEST ERRORR")
    ports = context.ports

    logger.info("Verifying sensor client is in context")

    sensor_client = getattr(context, "sensor_client", None)
    if sensor_client is None:
        raise RuntimeError("Did not find sensor client")

    streamid = ports.input_stream.stream_id
    logger.info(f"Getting obverstations from {streamid}")

    obs = sensor_client.get_observations(streamid=streamid, limit=5)

    logger.info(f"Got observations {obs['results']}")
