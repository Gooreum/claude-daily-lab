import requests

BASE = "https://api.anthropic.com/v1/organizations"
keys = requests.get(f"{BASE}/api_keys").json()["data"]
for k in keys:
    ws = k["workspace_id"] or "default"
    print(k["name"], ws)

groups = requests.get(f"{BASE}/rbac_groups").json()["data"]
for g in groups:
    print(g["roles"])
for rl in requests.get(f"{BASE}/rbac_roles").json()["data"]:
    print(rl["name"])
limits = requests.get(f"{BASE}/rate_limits").json()["data"]
print([x["group_type"] for x in limits])
