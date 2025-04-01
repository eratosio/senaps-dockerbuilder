import os
from eratos_docker.run import ModelRunner
from docker import APIClient

streamid = "bom_gov_au.94776.air.air_temp"

docker_client = APIClient()
runner = ModelRunner(
    "examples/get_stream",
    docker_client,
)
runner.run_model(
    initial_ports={"input_stream": streamid},
    senaps_host="senaps.eratos.com",
    senaps_api_key=os.environ["SENAPS_KEY"],
)
