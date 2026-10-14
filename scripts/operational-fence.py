"""Provision or rotate a nonsecret external generation independently of business snapshots."""

import argparse
import json
import os
from pathlib import Path
from uuid import UUID, uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["init", "rotate"])
    parser.add_argument("--path", type=Path, required=True)
    args = parser.parse_args()
    path = args.path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if args.operation == "init":
        value = {"deployment_id": str(uuid4()), "generation_id": str(uuid4())}
        with path.open("x", encoding="utf-8") as output:
            json.dump(value, output)
    else:
        previous = json.loads(path.read_text(encoding="utf-8"))
        value = {
            "deployment_id": str(UUID(previous["deployment_id"])),
            "generation_id": str(uuid4()),
        }
        staged = path.with_name(path.name + "." + str(uuid4()) + ".pending")
        with staged.open("x", encoding="utf-8") as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(staged, path)
    print("External generation provisioned; register and requalify before binding or movement.")
    print("Keep this file outside every business-database restore set.")


if __name__ == "__main__":
    main()
