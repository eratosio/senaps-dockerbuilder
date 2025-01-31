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
    list_packages()

    # check senaps logging working correctly
    logger = logging.getLogger()
    logger.debug("THIS IS A TEST DEBUG MESSAGE")
    logger.info("THIS IS A TEST MESSAGE")
    logger.warning("THIS IS A TEST WARNING")
    logger.error("THIS IS A TEST ERRORR")
    ports = context.ports

    x = json.loads(ports.input0.value)
    print(f"Input 0 value : {x}")
    y = json.loads(ports.input1.value)
    print(f"Input 1 value : {y}")

    print(f"Sum : {x+y}")

    ports.output.value = str(x + y)
