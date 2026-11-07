#!/usr/bin/env python3
"""Convert a locally saved CloudFormation describe-stacks JSON to PUBLIC config."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outputs", type=Path)
    parser.add_argument("--output", type=Path, default=Path("migration/private/app-config.json"))
    args = parser.parse_args()
    value = json.loads(args.outputs.read_text())
    outputs = {r["OutputKey"]: r["OutputValue"] for r in value["Stacks"][0]["Outputs"]}
    config = {"appUrl": outputs["AppUrl"], "apiUrl": outputs["ApiUrl"], "region": outputs["Region"],
              "issuer": f'https://cognito-idp.{outputs["Region"]}.amazonaws.com/{outputs["UserPoolId"]}',
              "clientId": outputs["ClientId"], "cognitoDomain": outputs["CognitoDomain"]}
    if config["region"] != "us-east-1":
        raise ValueError("Only the approved us-east-1 region is supported by this template's CSP.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Wrote public configuration to {args.output}")


if __name__ == "__main__":
    main()
