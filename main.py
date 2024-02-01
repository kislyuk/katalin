"""
python-code-advisor: a GitHub Action to generate LLM-assisted pull request suggestions.

See README.md for more information.
"""
import ast
import json
import logging
import os
import textwrap
from collections import defaultdict

import requests
from openai import OpenAI
from unidiff import PatchSet

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

prompt = """
Given the following Python file:
```
{content}
```
please provide a concise Python docstring for the {documentable_name} {documentable_type}, with a human readable description of the purpose of the {documentable_type}, and a Sphinx annotation of its input parameters and output value. Provide the text of the docstring directly, without any quotation marks or method signature.
"""

SUGGESTION_TEMPLATE = """
#### _Suggested documentation improvement_
It looks like this class, method, or function has no docstring.
```suggestion
{original_line}{body}
```
_You can edit or replace the proposed docstring before committing it by clicking the "..." menu._
"""

openai_client = OpenAI()
openai_model_name = os.environ.get("OPENAI_MODEL_NAME", "gpt-3.5-turbo-0125")
pr_url = ""
pr_head_sha = ""
github_headers = {}


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
    logger.info(res.text)
    res.raise_for_status()
    return res.json()


def get_suggested_docstring(prompt, **format_args):
    chat_completion = openai_client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": prompt.format(**format_args),
            }
        ],
        model=openai_model_name,
    )
    docstring = chat_completion.choices[0].message.content
    docstring = docstring.replace('"""', "")
    docstring = textwrap.fill(docstring, replace_whitespace=False, width=116)
    docstring = textwrap.indent(docstring, " " * 4)
    docstring = f'    """\n{docstring}\n    """'
    return docstring


def suggest_docstring(filename, line, documentable, source):
    logger.info("Processing: %s", line)
    suggested_docstring = get_suggested_docstring(
        prompt,
        content=source,
        documentable_name=documentable["name"],
        documentable_type=documentable["type"],
    )
    logger.info("Will add comment at %s:%s", filename, line.target_line_no)
    add_comment(
        pr_url=pr_url,
        headers=github_headers,
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


def get_docstring_lineno(documentable, all_lines):
    first_body_lineno = documentable["first_body_lineno"] - 1
    while True:
        if first_body_lineno not in all_lines:
            break
        if all_lines[first_body_lineno].value.strip().startswith("#"):
            first_body_lineno -= 1
        else:
            return first_body_lineno


def scan_diff(pr_url, headers):
    for patch in PatchSet(get_diff(pr_url, headers)):
        logger.info("Processing patch %s", patch.__dict__)
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
        try:
            module = ast.parse(source)
        except Exception as e:
            logger.info("Error parsing %s: %s", patch.target_file, e)
            continue
        documentables = get_documentables(module)

        all_lines = {}
        for hunk in patch:
            for line in hunk:
                if line.line_type == "+":
                    all_lines[line.target_line_no] = line

        for hunk in patch:
            logger.info("Processing hunk %s", hunk.__dict__)
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
                docstring_lineno = get_docstring_lineno(documentable, all_lines)
                if not documentable["has_docstring"]:
                    suggest_docstring(
                        patch.target_file[2:],
                        all_lines[docstring_lineno],
                        documentable,
                        source,
                    )


if __name__ == "__main__":
    logger.info("python-code-advisor starting")
    github_headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    }

    github_event = json.loads(os.environ["GITHUB_EVENT"])
    enabled_advisors = os.environ["ENABLED_ADVISORS"].splitlines(keepends=False)

    pr_url = github_event["pull_request"]["url"]
    pr_head_sha = github_event["pull_request"]["head"]["sha"]
    pr_labels = [label["name"] for label in github_event["pull_request"]["labels"]]
    for label in pr_labels:
        for advisor in enabled_advisors:
            if label == f"skip-{advisor}":
                enabled_advisors.remove(advisor)
    logger.info("Enabled advisors: %s", enabled_advisors)
    if "docstrings" in enabled_advisors:
        scan_diff(pr_url, headers=github_headers)
    else:
        logger.info("Skipping docstrings advisor")
