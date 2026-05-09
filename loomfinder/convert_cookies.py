import json
from pathlib import Path

path = Path.home() / ".loomfinder" / "cookies.json"
data = json.loads(path.read_text())

# data is already a list of cookie objects
converted = {item["name"]: item["value"] for item in data}

path.write_text(json.dumps(converted, indent=2))
print(f"Converted {len(converted)} cookies to dictionary format.")
