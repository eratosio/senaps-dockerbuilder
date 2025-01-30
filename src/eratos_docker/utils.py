import platform
import os
import json
from pathlib import Path


def get_appdata() -> str:
    if platform.system() == "Windows":
        localappdata = os.getenv("LOCALAPPDATA")  # Local
        localappdata = os.path.join(localappdata, "eratos", "docker")
    else:
        # For Unix-like systems (Linux, macOS)
        home = os.getenv("HOME")  # Use home directory on Unix-based OS
        localappdata = os.path.join(home, ".local", "share", "eratos", "docker")
    if not os.path.exists(localappdata):
        os.makedirs(localappdata, exist_ok=True)
    return localappdata


REGISTRY_DIR = os.path.join(get_appdata(), "registry.json")


def register_model(path: str, image: str, manifest: dict):
    if not os.path.exists(REGISTRY_DIR):
        registry = {"image": image, "manifest": manifest}
    else:
        with open(REGISTRY_DIR, "r") as f:
            registry = json.load(f)
            registry[path] = {"image": image, "manifest": manifest}
    with open(REGISTRY_DIR, "w") as f:
        json.dump(registry, f, indent=4)


def get_registry():
    with open(REGISTRY_DIR, "r") as f:
        registry = json.load(f)
        return registry


def get_registry_entry(path):
    return get_registry()[path]
