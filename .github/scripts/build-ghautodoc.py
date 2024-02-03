import json
import os

import requests

print("ghautodoc")

github_context = json.loads(os.environ["GITHUB_CONTEXT"])

pr_url = github_context["event"]["pull_request"]["url"]
diff_url = github_context["event"]["pull_request"]["diff_url"]

headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {github_context['token']}",
}

res = requests.get(diff_url, headers=headers)
res.raise_for_status()

print(res.content)
