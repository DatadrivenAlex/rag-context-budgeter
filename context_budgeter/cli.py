import argparse
import json
import sys
from pathlib import Path

from context_budgeter.packer import PackRequest, pack


def main():
    parser = argparse.ArgumentParser(
        description="Pack trusted local RAG chunks within a byte budget"
    )
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    try:
        request = PackRequest.model_validate(json.loads(args.request.read_text()))
        result = pack(request)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    return 0
