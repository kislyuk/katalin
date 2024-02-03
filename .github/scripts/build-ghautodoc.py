import json
import os

import requests
from unidiff import PatchSet

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
    print(res.text)
    res.raise_for_status()
    return res.json()


# def parse_patch_header(patch: str):
#     for line in patch.splitlines():
#         if re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))?\ @@[ ]?(.*)", line):
#     return re.findall(r"@@ -(.+?) \+(.+?) @@", "@@ -0,0 +1 @@\n+a")


SUGGESTION_TEMPLATE = """
### Suggested documentation improvement
The banana documentation system has detected that this class, method, or function has no docstring.

Here is a proposed docstring for this class, method, or function:
```suggestion
{body}
```
You can edit or replace the proposed docstring before committing it by clicking the "..." menu.

_This is a test of the automated banana documentation system. This is only a test._
"""


# https://api.github.com/repos/OWNER/REPO/pulls/PULL_NUMBER/comments \
#  -d '{"body":"Great stuff!","commit_id":"6dcb09b5b57875f334f61aebed695e2e4193db5e",
#       "path":"file1.txt","start_line":1,"start_side":"RIGHT","line":2,"side":"RIGHT"}'


def suggest_docstring(patch, hunk, line):
    print("Processing:", line)
    print("Will add comment at", patch.source_file[2:], hunk.source_start)
    add_comment(
        pr_url=pr_url,
        headers=headers,
        body=SUGGESTION_TEMPLATE.format(body=f"This is a suggestion for {hunk}"),
        commit_id=pr_head_sha,
        path=patch.source_file[2:],
        line=line.diff_line_no,
    )


for patch in PatchSet(get_diff(pr_url, headers)):
    for hunk in patch:
        for line in hunk:
            if line.line_type != "+":
                continue
            if line.value.startswith("def ") or line.value.startswith("class "):
                suggest_docstring(patch, hunk, line)


# for file_change in get_files(pr_url, headers):
#     for source_offset, target_offset in parse_patch_header(file_change["patch"]):
#         source_offset_start = int(source_offset.split(",")[0])
#         # TODO: extract lines from patch
#         add_comment(
#             pr_url=pr_url,
#             headers=headers,
#             body=SUGGESTION_TEMPLATE.format(
#                 body=f"This is a suggestion for {file_change}"
#             ),
#             commit_id=pr_head_sha,
#             path=file_change["filename"],
#             line=source_offset_start + 1,
#         )
