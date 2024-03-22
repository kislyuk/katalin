# katalin GitHub action

This is a GitHub action that generates LLM-assisted suggestions for improving Python code in PRs, and posts them as PR
comments.

See [this sample PR](https://github.com/kislyuk/katalin/pull/48) for an example of katalin in action.

## Inputs

### `openai-api-token`

**Required** The OpenAI API token to use.

### `enabled-advisors`

A newline-separated list of advisor modules to enable. Available advisors are:

* `docstrings`: Provides doscstring suggestions for undocumented Python modules, functions, classes, and methods.
* `security`: Provides comments regarding potential security concerns.
* `logic-check`: Identifies possible logic errors.

<!--
### `custom-prompts`

A newline-separated list of colon-separated `node:prompt` pairs. TODO
-->

## Example usage

```yaml
uses: kislyuk/katalin@v1
with:
  openai-api-key: ${{secrets.OPENAI_API_KEY}}
  enabled-advisors: |-
    docstrings
    security
    logic-check
```

See
[Using secrets in GitHub Actions](https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions)
for details on how to set the secret above.
