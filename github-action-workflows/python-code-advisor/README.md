# python-code-advisor GitHub action

This is a Color internal action that generates LLM-assisted suggestions for improving Python code in PRs, and posts them
as PR comments.

## Inputs

### `openai-api-token`

**Required** The OpenAI API token to use.

### `github-token`

**Required** The GitHub API token to use. Should be set automatically.

### `github-event`

**Required** The details of the GitHub PR event. Should be set automatically.

## Outputs

None

## Example usage

```yaml
uses: color/github-action-workflows/python-code-advisor@main
with:
  openai-api-token: ${{secrets.GITHUB_TOKEN}}
```
