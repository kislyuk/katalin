import ast
import json
import os
from collections import defaultdict

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
    side: str = "RIGHT",
):
    res = requests.post(
        f"{pr_url}/comments",
        headers=headers,
        json=dict(
            body=body,
            commit_id=commit_id,
            path=path,
            line=line,
            side=side,
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
### _Suggested documentation improvement_
It looks like this class, method, or function has no docstring. Here is a suggestion:
```suggestion
{original_line}{body}
```
_You can edit or replace the proposed docstring before committing it by clicking the "..." menu._
"""


# https://api.github.com/repos/OWNER/REPO/pulls/PULL_NUMBER/comments \
#  -d '{"body":"Great stuff!","commit_id":"6dcb09b5b57875f334f61aebed695e2e4193db5e",
#       "path":"file1.txt","start_line":1,"start_side":"RIGHT","line":2,"side":"RIGHT"}'


def suggest_docstring(filename, line):
    print("Processing:", line)
    print("Will add comment at", filename, line.target_line_no)
    add_comment(
        pr_url=pr_url,
        headers=headers,
        body=SUGGESTION_TEMPLATE.format(
            original_line=line.value,
            body=f'    """This is a doctring for {line.value}"""',
        ),
        commit_id=pr_head_sha,
        path=filename,
        line=line.target_line_no,
    )


def has_docstring(node):
    if isinstance(node.body[0], ast.Constant):
        if isinstance(node.body[0].value, str):
            return True
    return False


def get_node_annotation(node, node_type):
    return {
        "type": node_type,
        "name": node.name,
        "has_docstring": has_docstring(node),
        "first_body_lineno": node.body[0].lineno,
    }


def get_documentables(module_node):
    documentables = defaultdict(dict)
    for node in module_node.body:
        if isinstance(node, ast.FunctionDef):
            documentables[node.lineno] = get_node_annotation(node, "function")
        elif isinstance(node, ast.ClassDef):
            documentables[node.lineno] = get_node_annotation(node, "class")
            for subnode in node.body:
                if isinstance(subnode, ast.FunctionDef):
                    documentables[subnode.lineno] = get_node_annotation(
                        subnode, "method"
                    )
    return documentables


def scan_diff(pr_url, headers):
    for patch in PatchSet(get_diff(pr_url, headers)):
        print("Processing patch", patch.__dict__)
        if not patch.target_file.endswith(".py"):
            continue
        with open(patch.target_file[2:], "r") as f:
            source = f.read()
        module = ast.parse(source)
        documentables = get_documentables(module)

        for hunk in patch:
            print("Processing hunk", hunk.__dict__)
            for line in hunk:
                if line.line_type != "+":
                    continue
                if line.value.startswith("def ") or line.value.startswith("class "):
                    if documentables.get(line.target_line_no):
                        if not documentables[line.target_line_no]["has_docstring"]:
                            suggest_docstring(patch.target_file[2:], line)


scan_diff(pr_url, headers)
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
