from eratos_docker.run import ModelRunner
from docker import APIClient

docker_client = APIClient()
runner = ModelRunner(
    "examples/csiro.operators.snap-model-at-polygon-0.0.1",
    docker_client,
)
g = "POLYGON ((138.624287 -33.325508, 138.665657 -33.325508, 138.665657 -33.294521, 138.624287 -33.294521, 138.624287 -33.325508))"
night_of = "2024-09-17"
t = 1

runner.run_model(docs={"input_geom":g,
                       "input_Night_of":night_of,
                       "input_threshold":t,
                       "config": {'anything': 'e'},
                       "secrets": {"id": "OS6QNMANYGL55VNL3DNZELHU",
                                   "secret": "c6T9spGQtl3HfKrd0g0SeeM7HJBFqdmWT7N3FhrSke0="}})
