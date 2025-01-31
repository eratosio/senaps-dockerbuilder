# Usage

Install the package, the only dependency is the Python docker client, so realistically it's okay to install system-wide / userspace `site-packages`.

```sh
pip install .
```

## Building Senaps Models

A directory can be provided,

```sh
senaps-dockerbuild examples/simple
```

which will output a `dockerfile` to `docker/`.

A zip file can also be produced, which will also unzip the model to `docker/{model}`

```sh
senaps-dockerbuild examples/simple.zip
```

## Running Models

```sh
python scripts/run_example.py
```

The main bit of code is as follows

```python
docker_client = APIClient()
runner = ModelRunner(MODEL_PATH, docker_client)
runner.run_model()
```

`MODEL_PATH` can either be the path to an archive or directory that has previously been built by the tool above. This works by looking at a simple key value store in `~/.local/share/eratos/docker/registry.json` (Linux, OSX) or `%LOCALAPPDATA%\eratos\docker\registry.json` on Windows that is persisted by `senaps-dockerbuild`. This associates the full path of a Senaps model with an associated Docker image and its manifest.
