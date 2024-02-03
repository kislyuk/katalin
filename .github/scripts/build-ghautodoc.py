import json
import os

import requests

print("ghautodoc")

github_context = json.loads(os.environ["GITHUB_CONTEXT"])

pr_url = github_context["event"]["pull_request"]["url"]
# diff_url = github_context["event"]["pull_request"]["diff_url"]

headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {github_context['token']}",
}


def get_diff(pr_url: str, headers: dict) -> str:
    res = requests.get(
        pr_url,
        headers=dict(headers, Accept="application/vnd.github.v3.diff"),
        timeout=30,
    )
    res.raise_for_status()
    return res.text


def get_files(pr_url: str, headers: dict) -> list:
    res = requests.get(f"{pr_url}/files", headers=headers, timeout=30)
    res.raise_for_status()
    return res.json()


print(get_files(pr_url, headers))
