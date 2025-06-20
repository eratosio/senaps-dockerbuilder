import docker
import requests
import json
import time
import platform
import pprint
import multiprocessing
from .mock_analysis import MockAnalysisService
from .utils import get_registry_entry
from uuid import uuid4
from pathlib import Path
from docker import APIClient
from colorama import Fore, Style
from typing import Any, Optional

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
    def __init__(
        self,
        model_path: Optional[str | Path],
        docker_client: docker.APIClient,
    ):
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

    def run_model(
        self,
        initial_ports: Optional[dict[str, Any]] = None,
        id: Optional[str] = None,
        bind_mounts: Optional[dict[str, Any]] = None,
        bind_model_dir: bool = False,
        model_port: int = 28080,
        analysis_service_port: int = 18080,
        senaps_host: Optional[str] = None,
        expose_ports: Optional[list[int]] = None,
        senaps_api_key: Optional[str] = None,
    ):
        # Spin up a mock Analysis Service to capture uploaded documents.
        httpd = MockAnalysisService(analysis_service_port)
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

        job_request = {
            "modelId": id,
            "analysisServicesConfiguration": {
                "url": f"http://host.docker.internal:{analysis_service_port}/api/analysis"
            },
        }

        if senaps_host:
            if not senaps_api_key:
                raise ValueError("Senaps host specified but no API key was provided")

            job_request["sensorCloudConfiguration"] = {
                "url": f"{senaps_host}/api/sensor/v2",
                "apiKey": senaps_api_key,
            }

        if initial_ports is None:
            initial_ports = {}
        ports = {}
        doc_map = {}
        for port_config in model["ports"]:
            port_name = port_config.get("portName")
            input_val = initial_ports.get(port_name, "")
            mockid = str(uuid4())
            doc_map[mockid] = port_name
            if port_config["type"] == "stream":
                if "sensorCloudConfiguration" not in job_request:
                    raise ValueError(
                        "Stream port specified but not sensor client configuration"
                    )
                if not isinstance(input_val, str):
                    raise ValueError("Stream id should be a string")
                ports[port_name] = {"streamId": input_val}
            else:
                ports[port_name] = {
                    "document": json.dumps(input_val)
                    if not isinstance(input_val, str)
                    else input_val,
                    "documentId": mockid,
                }

        job_request["ports"] = ports

        if bind_model_dir:
            if self.model_path is None:
                raise ValueError("Runner does not have a model path configured")

            if bind_mounts is None:
                bind_mounts = {self.model_path.resolve().as_posix(): "/opt/model"}
            else:
                bind_mounts.update({self.model_path.resolve().as_posix(): "/opt/model"})

        if bind_mounts is not None:
            binds = {
                host_dir: {"bind": container_dir, "mode": "rw"}
                for host_dir, container_dir in bind_mounts.items()
            }
            volumes = list(bind_mounts.values())
        else:
            binds = None
            volumes = []

        host_config = self.docker_client.create_host_config(
            network_mode="bridge",
            port_bindings={model_port: model_port},
            extra_hosts={"host.docker.internal": "host-gateway"},
            binds=binds,
        )

        if expose_ports is None:
            ports = [model_port]
        else:
            ports = [model_port] + expose_ports

        container = self.docker_client.create_container(
            self.image_name,
            host_config=host_config,
            detach=True,
            ports=ports,
            volumes=volumes,
            environment={"MODEL_PORT": f"{model_port}", "MODEL_HOST": "0.0.0.0"},
            tty=True,
            platform="linux/amd64",
        )
        container_id = container.get("Id")
        self.docker_client.start(container_id)

        print("Model container running: {}".format(container_id))

        model_url = f"http://localhost:{model_port}/"

        status = None
        model_errors = None
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
            print("Submitting job request:")
            pprint.pprint(job_request, indent=4)

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

            if status.get("state") == "FAILED":
                model_errors = status.get("exception")
                print(f"Model failed with exception {model_errors['msg']}")
            else:
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
            border = "=" * 40
            print(
                f"{Style.BRIGHT}{border} {Fore.CYAN}DOCKER LOG{Fore.BLACK} {border}{Style.RESET_ALL}"
            )
            docker_logs = self.docker_client.logs(container_id).decode("utf-8")
            for msg in docker_logs.split("\n"):
                print(f"{Fore.CYAN}>{Style.RESET_ALL} {msg}")

            print(
                f"{Style.BRIGHT}{border} {Fore.CYAN}DOCKER LOG{Fore.BLACK} {border}{Style.RESET_ALL}"
            )

            # Wait 10 seconds for container to exit, then clean up.
            print("Killing container")
            self.docker_client.stop(container_id, timeout=10)
            print("Removing container")

            # Force kill if the container hasn't died naturally.
            self.docker_client.remove_container(container_id, v=True, force=True)

        result_docs = {doc_map[id]: val for id, val in httpd.documents.items()}
        # puts input docs in
        result_docs.update(initial_ports)

        print("Document state:")
        pprint.pprint(result_docs, indent=4)
        if model_errors:
            print("Errors:")
            pprint.pprint(model_errors, indent=4)
        else:
            print("Errors: none")

        return result_docs, model_errors
