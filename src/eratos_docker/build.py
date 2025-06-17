from pathlib import Path
from typing import Optional, Annotated
from .utils import register_model, get_registry_entry
import tarfile
import zipfile
import json
import os
import docker
import platform
import argparse
import shutil
import sys
import tempfile
import typer
from colorama import Fore, Style
from io import BytesIO

BASE_IMAGE_MAP = {
    "6cd2f899-b5f1-444b-afbe-ee4a4eaec1bc": "senaps-prod/base-images/python3.10-base",
    "B415DE8D-4886-4E43-B33A-692DB431C99E": "base-images/python:3.8",
    "47861a5e-6180-4913-b77a-0b8dd30f8b46": "base-images/r4-geospatial",
    "88bb0ad8-c24f-405c-890f-77a09a75926f": "base-images/r4",
}
URI_BASE = "public.ecr.aws/eratosio"
app = typer.Typer()


def get_docker_base_url():
    system = platform.system()
    if system == "Linux" or system == "Darwin":  # macOS
        return "unix://var/run/docker.sock"
    elif system == "Windows":
        return "npipe:////./pipe/docker_engine"
    else:
        raise ValueError(f"Unsupported platform: {system}")


def get_client_output_lines(lines):
    line_collection = (
        lines.decode("utf-8").strip("\r\n").split("\r\n")
    )  # don't ask me why it uses windows line endings...
    json_objects = []
    for line in line_collection:
        try:
            json_object = json.loads(line)
            json_objects.append(json_object)
        except Exception as err:
            print(
                "Aiie! failed to parse output line. Line was: {0}. Error was: {1}".format(
                    lines.decode("utf-8"), err
                )
            )
    return json_objects


def print_lines(lines):
    for line in lines:
        prefix, text = (
            ("\033[1;31m!\033[0;0m ", line["error"])
            if "error" in line
            else ("\033[1;36m>\033[0;0m ", line.get("stream", ""))
        )
        print(prefix + text.strip(), flush=True)


def extract_archive(path: Path, dst: Path):
    if Path.exists(dst):
        shutil.rmtree(dst)
    if path.suffix == ".gz":
        with tarfile.open(path, "r:gz") as tar:
            tar.extractall(path=dst)

    elif path.suffix == ".zip":
        with zipfile.ZipFile(path, "r") as zip_ref:
            zip_ref.extractall(path=dst)


@app.command("build")
def build(
    path: Path,
    tag: Annotated[str, typer.Option(help="tag for image, else latest")] = "latest",
    repo_name: Annotated[Optional[str], typer.Option(help="repo name of image")] = None,
):
    docker_client = docker.APIClient(base_url=get_docker_base_url())
    os.makedirs("docker", exist_ok=True)
    dockerfile_dir = Path("docker")

    if path.suffix in [".gz", ".tar.gz", ".zip"]:
        filename = path.stem
        if filename.endswith(".tar"):
            filename = filename.replace(".tar", "")
        model_path = dockerfile_dir / filename
        extract_archive(path, dockerfile_dir / filename)
        dockerfile_name = filename
    else:
        model_path = path
        dockerfile_name = path.as_posix().replace("/", ".")

    dockerfile_path = dockerfile_dir / f"{dockerfile_name}.dockerfile"

    if not Path.exists(model_path / "manifest.json"):
        raise FileNotFoundError(f"No manifest.json in {model_path}")

    with open(model_path / "manifest.json", "r") as f:
        manifest = json.load(f)

    base_image_id = manifest["baseImage"]
    base_image_name = BASE_IMAGE_MAP[base_image_id]
    base_image_uri = f"{URI_BASE}/{base_image_name}"
    # resolve dependencies
    pip_deps = []
    apt_deps = []
    # todo R
    entrypoint = manifest["entrypoint"]
    for entry in manifest["dependencies"]:
        match entry["provider"]:
            case "PIP":
                pip_deps.append(entry["name"])
            case "APT":
                apt_deps.append(entry["name"])
            case _:
                raise ValueError(f"Invalid dependency provider {entry['provider']}")

    print("Building dockerfile")
    with open(dockerfile_path, "w") as f:
        # see https://github.com/eratosio/analysis-service-api/blob/eratos-develop/docker/src/main/java/au/csiro/sensorcloud/analysis/docker/EcsRuntimeManager.java#L261
        f.writelines(
            [
                f"# Automatically generated docker file for {path.as_posix()} on\n",
                f"FROM {base_image_uri}\n",
                f"COPY {model_path} /opt/model/\n",
            ]
        )
        if len(apt_deps) > 0:
            f.write(
                f"RUN apt-get -y -q update && DEBIAN_FRONTEND=noninteractive apt-get -y -q install {' '.join(apt_deps)}\n"
            )

        if len(pip_deps) > 0:
            f.write(f"RUN pip install --no-cache-dir {' '.join(pip_deps)}\n")

        f.writelines(
            [
                # Install dependencies
                "RUN python3 -OO -m compileall /opt/model/\n",
                "WORKDIR /opt/model\n",
                f"ENTRYPOINT python3 -m as_models host /opt/model/{entrypoint}\n",
            ]
        )

    # by default, name the repository as the following
    if repo_name is None:
        repo_name = f"{Path.cwd().stem}/{dockerfile_name}"
        repo_name = repo_name.lower()

    register_model(path.resolve().as_posix(), repo_name, manifest)

    print(f" - {dockerfile_path}")
    print("\nBuilding image . Docker output follows...")
    print(
        f"{Style.BRIGHT}{Fore.BLACK}(Note: lines preceded by "
        f"{Fore.CYAN}>{Fore.BLACK} denote STDOUT output from Docker, and lines preceded by "
        f"{Fore.RED}!{Fore.BLACK} denote STDERR output.){Style.RESET_ALL}\n"
    )

    for line in docker_client.build(
        path=".",
        dockerfile=dockerfile_path.as_posix(),
        platform="linux/amd64",
        tag=f"{repo_name}:{tag}",
    ):
        try:
            print_lines(get_client_output_lines(line))
        except Exception as e:
            print(line)

    return 0


@app.command("recompile")
def rebuild(path: Path, from_tag: str = "latest", to_tag: str = "latest"):
    docker_client = docker.APIClient(base_url=get_docker_base_url())
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist!")
    model_cfg = get_registry_entry(path.resolve().as_posix())
    image_name = model_cfg["image"]
    with open(path / "manifest.json", "r") as f:
        manifest = json.load(f)
    entrypoint = manifest["entrypoint"]
    dockerlines = [
        f"FROM {image_name}:{from_tag}\n",
        f"COPY {path} /opt/model/\n",
        "RUN python3 -OO -m compileall /opt/model/\n",
        "WORKDIR /opt/model\n",
        f"ENTRYPOINT python3 -m as_models host /opt/model/{entrypoint}\n",
    ]

    with tempfile.NamedTemporaryFile(suffix=".dockerfile", dir=".") as dockerfile:
        dockerfile.writelines([x.encode("utf-8") for x in dockerlines])
        # otherwise race condition occurs where file is not written to fast enough
        dockerfile.flush()
        print("\nBuilding image . Docker output follows...")
        print(
            f"{Style.BRIGHT}{Fore.BLACK}(Note: lines preceded by "
            f"{Fore.CYAN}>{Fore.BLACK} denote STDOUT output from Docker, and lines preceded by "
            f"{Fore.RED}!{Fore.BLACK} denote STDERR output.){Style.RESET_ALL}\n"
        )

        for line in docker_client.build(
            path=".",
            dockerfile=dockerfile.name,
            platform="linux/amd64",
            tag=f"{image_name}:{to_tag}",
        ):
            try:
                print_lines(get_client_output_lines(line))
            except Exception as e:
                print(line)

        pass
