import ast
import json
import os
import textwrap
from collections import defaultdict

import requests
from openai import OpenAI
from unidiff import PatchSet

print("ghautodoc")

github_context = json.loads(os.environ["GITHUB_CONTEXT"])

pr_url = github_context["event"]["pull_request"]["url"]
pr_head_sha = github_context["event"]["pull_request"]["head"]["sha"]
# diff_url = github_context["event"]["pull_request"]["diff_url"]

prompt = """
Given the following Python file:
```
{content}
```
please provide a concise Python docstring for the {documentable_name} {documentable_type}, with a human readable description of the purpose of the {documentable_type}, and a Sphinx annotation of its input parameters and output value. Provide the text of the docstring directly, without any quotation marks or method signature.
"""

headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {github_context['token']}",
}

openai_client = OpenAI()


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
#### _Suggested documentation improvement_
It looks like this class, method, or function has no docstring.
```suggestion
{original_line}{body}
```
_You can edit or replace the proposed docstring before committing it by clicking the "..." menu._
"""


# https://api.github.com/repos/OWNER/REPO/pulls/PULL_NUMBER/comments \
#  -d '{"body":"Great stuff!","commit_id":"6dcb09b5b57875f334f61aebed695e2e4193db5e",
#       "path":"file1.txt","start_line":1,"start_side":"RIGHT","line":2,"side":"RIGHT"}'


def get_suggested_docstring(prompt, **format_args):
    # FIXME: only suggest for names that are unique at top level?
    # e.g. what to do about Foo.get() vs. Bar.get()?
    chat_completion = openai_client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": prompt.format(**format_args),
            }
        ],
        model="gpt-3.5-turbo-1106",
    )
    docstring = chat_completion.choices[0].message.content
    docstring = docstring.replace('"""', "")
    docstring = textwrap.fill(docstring, replace_whitespace=False)
    docstring = textwrap.indent(docstring, " " * 4)
    docstring = f'    """\n{docstring}\n    """'
    return docstring


def suggest_docstring(filename, line, documentable, source):
    print("Processing:", line)
    suggested_docstring = get_suggested_docstring(
        prompt,
        content=source,
        documentable_name=documentable["name"],
        documentable_type=documentable["type"],
    )
    print("Will add comment at", filename, line.target_line_no)
    add_comment(
        pr_url=pr_url,
        headers=headers,
        body=SUGGESTION_TEMPLATE.format(
            original_line=line.value, body=suggested_docstring
        ),
        commit_id=pr_head_sha,
        path=filename,
        line=line.target_line_no,
    )


def has_docstring(node):
    if isinstance(node.body[0], ast.Expr):
        if isinstance(node.body[0].value, ast.Constant):
            if isinstance(node.body[0].value.value, str):
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
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            documentables[node.lineno] = get_node_annotation(node, "function")
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            documentables[node.lineno] = get_node_annotation(node, "class")
            for subnode in node.body:
                if isinstance(subnode, ast.FunctionDef):
                    if subnode.name.startswith("_"):
                        continue
                    documentables[subnode.lineno] = get_node_annotation(
                        subnode, "method"
                    )
    return documentables


def scan_diff(pr_url, headers):
    for patch in PatchSet(get_diff(pr_url, headers)):
        print("Processing patch", patch.__dict__)
        if not patch.target_file.endswith(".py"):
            continue
        if any(
            f"/{x}/" in patch.target_file for x in ["tests", "migrations", "backfills"]
        ):
            continue
        with open(patch.target_file[2:], "r") as f:
            source = f.read()
        if "```" in source:
            continue
        module = ast.parse(source)
        documentables = get_documentables(module)

        all_lines = {}
        for hunk in patch:
            for line in hunk:
                if line.line_type == "+":
                    all_lines[line.target_line_no] = line

        for hunk in patch:
            print("Processing hunk", hunk.__dict__)
            for line in hunk:
                if line.line_type != "+":
                    continue
                if not (
                    line.value.startswith("def ") or line.value.startswith("class ")
                ):
                    continue
                if line.target_line_no not in documentables:
                    continue
                documentable = documentables[line.target_line_no]
                if documentable["first_body_lineno"] - 1 not in all_lines:
                    continue
                if not documentable["has_docstring"]:
                    suggest_docstring(
                        patch.target_file[2:],
                        all_lines[documentable["first_body_lineno"] - 1],
                        documentable,
                        source,
                    )


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
