import docker
import requests
import json
import time
from .mock_analysis import MockAnalysisService
from .utils import get_registry_entry
from uuid import uuid4
from pathlib import Path
from docker import APIClient
from colorama import Fore, Style

COLOURS = {
    "DEBUG": Fore.BLUE,
    "STDOUT": Fore.BLUE,
    "INFO": Fore.GREEN,
    "WARNING": Fore.YELLOW,
    "ERROR": Fore.RED,
    "STDERR": Fore.RED,
    "CRITICAL": Fore.MAGENTA,
}

TIMESTAMP_COLOUR = Fore.CYAN


def format_status(status):
    logs = status.get("log")
    if logs is None:
        return
    if len(logs) == 0:
        return
    else:
        for log in logs:
            level = log.get("level")
            message = log.get("message")
            timestamp = log.get("timestamp")
            print(
                f"{TIMESTAMP_COLOUR} [{timestamp}]{Style.RESET_ALL} {COLOURS[level]}{level}{Style.RESET_ALL}: {message}"
            )


class ModelRunner:
    def __init__(self, model_path: str | Path, docker_client: docker.APIClient):
        self.model_path = model_path
        self.docker_client = docker_client

        self.model_path = Path(self.model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(f"{model_path} does not exist!")
        model_cfg = get_registry_entry(self.model_path.resolve().as_posix())
        self.image_name = model_cfg["image"]
        manifest = model_cfg["manifest"]

        models = manifest["models"]
        self.model_ids = []
        self.models = {}
        for m in models:
            self.model_ids.append(m["id"])
            self.models[m["id"]] = m

        try:
            self.docker_client.inspect_image(self.image_name)
        except docker.errors.ImageNotFound:
            print(
                f"Could not find image {self.image_name}, try running as_models build {self.model_path}"
            )
            return False

    def run_model(self, docs=None, id=None, model_port=28080):
        # Spin up a mock Analysis Service to capture uploaded documents.
        httpd = MockAnalysisService()
        httpd.documents = {}
        httpd.timeout = 0.1
        # build context object
        if id is None:
            # default to first model
            #
            id = self.model_ids[0]
        else:
            if id not in self.models:
                raise KeyError("Invalid model id")
        model = self.models[id]

        if docs is None:
            docs = {}
        ports = {}
        for port_config in model["ports"]:
            port_name = port_config.get("port_name")
            input_doc = docs.get(port_name, "")
            ports[port_name] = {"document": input_doc, "documentId": str(uuid4())}

        job_request = {
            "modelId": id,
            "ports": ports,
            "analysisServicesConfiguration": {
                "url": "http://localhost:18080/api/analysis"
            },
        }
        host_config = self.docker_client.create_host_config(
            network_mode="host",
        )

        container = self.docker_client.create_container(
            self.image_name,
            host_config=host_config,
            detach=True,
            ports=[28080],
            environment={"MODEL_PORT": f"{model_port}", "MODEL_HOST": "0.0.0.0"},
            tty=True,
            platform="linux/amd64",
        )
        container_id = container.get("Id")
        self.docker_client.start(container_id)

        print("Model container running: {}".format(container_id))

        model_url = f"http://localhost:{model_port}/"

        status = None
        try:
            start_attempts = 0
            while True:
                try:
                    response = requests.get(model_url)
                    response.raise_for_status()

                    status = response.json()
                    print("Model listening at: {}".format(model_url))

                    break
                except requests.ConnectionError:
                    start_attempts += 1
                    if start_attempts > 5:
                        raise
                    time.sleep(1.0)

            # Start the model.
            requests.post(model_url, json=job_request).raise_for_status()

            # Poll until model completes.
            print("Running model...")
            try:
                while True:
                    httpd.handle_request()

                    response = requests.get(model_url)
                    response.raise_for_status()
                    status = response.json()
                    format_status(status)

                    if status.get("state") not in {"PENDING", "RUNNING"}:
                        break

                    time.sleep(0.5)
            except requests.exceptions.RequestException:
                pass

            print("Model complete. Cleaning up...")

            # Terminate the model.
            requests.post(
                model_url + "terminate", json={"timeout": 10.0}
            ).raise_for_status()
        except requests.HTTPError as e:
            print(e.response.text)

        except Exception as e:
            print(
                "Failed to start test model due to {}: {}".format(
                    e.__class__.__name__, e
                )
            )
            raise
        finally:
            print("Docker log follows:")

            print(self.docker_client.logs(container_id).decode("utf-8"))

        # Wait 10 seconds for container to exit, then clean up.
        self.docker_client.stop(container_id, timeout=10)

        # Force kill if the container hasn't died naturally.
        self.docker_client.remove_container(container_id, v=True, force=True)

        return status
