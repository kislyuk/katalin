import json
import os

import requests

print("ghautodoc")

github_context = json.loads(os.environ["GITHUB_CONTEXT"])

pr_url = github_context["event"]["pull_request"]["url"]
pr_head_sha = github_context["event"]["pull_request"]["head"]["sha"]
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


def add_comment(
    pr_url: str,
    headers: dict,
    body: str,
    commit_id: str,
    path: str,
    line: int,
):
    res = requests.post(
        f"{pr_url}/comments",
        headers=headers,
        json=dict(
            body=body,
            commit_id=commit_id,
            path=path,
            line=line,
        ),
        timeout=30,
    )
    res.raise_for_status()
    return res.json()


# https://api.github.com/repos/OWNER/REPO/pulls/PULL_NUMBER/comments \
#  -d '{"body":"Great stuff!","commit_id":"6dcb09b5b57875f334f61aebed695e2e4193db5e","path":"file1.txt","start_line":1,"start_side":"RIGHT","line":2,"side":"RIGHT"}'

for file_change in get_files(pr_url, headers):
    # TODO: extract lines from patch
    add_comment(
        pr_url=pr_url,
        headers=headers,
        body="test",
        commit_id=pr_head_sha,
        path=file_change["filename"],
        line=1,
    )