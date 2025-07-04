from eratos_docker.run import ModelRunner
from docker import APIClient

docker_client = APIClient()
runner = ModelRunner(
    "examples/simple",
    docker_client,
)
runner.run_model(initial_ports={"input0": "1", "input1": "2"})
