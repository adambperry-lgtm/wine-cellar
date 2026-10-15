"""Automated GitHub Pages Synchronizer for Sommelier Wine Cellar Agent.

Automatically pushes updates to the user's GitHub Pages repository (adambperry-lgtm/wine-cellar)
using the GitHub Personal Access Token configured in ~/.gemini/config/mcp_config.json
or the GITHUB_TOKEN environment variable.
"""

import os
import json
import base64
import urllib.request
import urllib.error
from typing import Optional, Dict, Any


DEFAULT_OWNER = "adambperry-lgtm"
DEFAULT_REPO = "wine-cellar"
DEFAULT_BRANCH = "main"
GITHUB_PAGES_URL = f"https://{DEFAULT_OWNER}.github.io/{DEFAULT_REPO}/"


def get_github_token() -> Optional[str]:
    """Retrieves the GitHub token from environment or Antigravity configuration."""
    # 1. Environment variables
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if token and token.strip():
        return token.strip()

    # 2. Antigravity MCP config
    mcp_path = os.path.expanduser("~/.gemini/config/mcp_config.json")
    if os.path.exists(mcp_path):
        try:
            with open(mcp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            servers = data.get("mcpServers", {})
            gh_server = servers.get("github-mcp-server") or servers.get("github")
            if gh_server and "env" in gh_server:
                t = gh_server["env"].get("GITHUB_PERSONAL_ACCESS_TOKEN") or gh_server["env"].get("GITHUB_TOKEN")
                if t and t.strip():
                    return t.strip()
        except Exception:
            pass

    # 3. Dedicated token file if present
    token_file = os.path.expanduser("~/.gemini/config/github_token.txt")
    if os.path.exists(token_file):
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                t = f.read().strip()
                if t:
                    return t
        except Exception:
            pass

    # 4. Project local token file (.github_token)
    project_token = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), ".github_token")
    if os.path.exists(project_token):
        try:
            with open(project_token, "r", encoding="utf-8") as f:
                t = f.read().strip()
                if t:
                    return t
        except Exception:
            pass

    return None


def prepare_distribution_files(base_dir: Optional[str] = None) -> str:
    """Prepares clean index_blank.html and for_github/index.html from web/index.html."""
    if not base_dir:
        # Default to repository root
        base_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

    full_index_path = os.path.join(base_dir, "web", "index.html")
    blank_index_path = os.path.join(base_dir, "web", "index_blank.html")
    github_index_path = os.path.join(base_dir, "for_github", "index.html")

    if not os.path.exists(full_index_path):
        raise FileNotFoundError(f"Source index.html not found at {full_index_path}")

    with open(full_index_path, "r", encoding="utf-8") as f:
        text = f.read()

    # Strip personal cellar bottles so GitHub Pages starts as a clean slate
    idx1 = text.find("const FALLBACK_BOTTLES = [")
    idx2 = text.find("async function loadData()", idx1) if idx1 != -1 else -1

    if idx1 != -1 and idx2 != -1:
        blank_content = text[:idx1] + "const FALLBACK_BOTTLES = [];\n\n    " + text[idx2:]
    else:
        blank_content = text

    with open(blank_index_path, "w", encoding="utf-8") as f:
        f.write(blank_content)

    os.makedirs(os.path.dirname(github_index_path), exist_ok=True)
    with open(github_index_path, "w", encoding="utf-8") as f:
        f.write(blank_content)

    return blank_content


def publish_to_github(
    commit_message: str = "Update wine cellar web application",
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
    branch: str = DEFAULT_BRANCH,
    target_path: str = "index.html",
    base_dir: Optional[str] = None
) -> Dict[str, Any]:
    """Pushes the prepared web application directly to GitHub Pages."""
    token = get_github_token()
    if not token:
        return {
            "success": False,
            "error": "GitHub token not found. Please verify token in ~/.gemini/config/mcp_config.json"
        }

    # 1. Prepare latest clean standalone HTML
    try:
        content_str = prepare_distribution_files(base_dir)
        content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("ascii")
    except Exception as e:
        return {"success": False, "error": f"Failed to prepare HTML for publish: {e}"}

    # 2. Get current file sha on GitHub
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{target_path}"
    headers = {
        "Authorization": f"token {token}",
        "User-Agent": "Wine-Cellar-Agent",
        "Accept": "application/vnd.github.v3+json"
    }

    current_sha = None
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            current_sha = data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            current_sha = None  # File does not exist yet
        else:
            return {"success": False, "error": f"GitHub API error fetching file info: {e.code} {e.reason}"}
    except Exception as e:
        return {"success": False, "error": f"Network error checking GitHub: {e}"}

    # 3. Commit and update file via PUT
    payload = {
        "message": commit_message,
        "content": content_b64,
        "branch": branch
    }
    if current_sha:
        payload["sha"] = current_sha

    put_data = json.dumps(payload).encode("utf-8")
    req_put = urllib.request.Request(api_url, data=put_data, headers={
        **headers,
        "Content-Type": "application/json"
    }, method="PUT")

    try:
        with urllib.request.urlopen(req_put) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            commit_sha = resp_data.get("commit", {}).get("sha", "unknown")
            return {
                "success": True,
                "commit_sha": commit_sha,
                "repo": f"{owner}/{repo}",
                "branch": branch,
                "pages_url": GITHUB_PAGES_URL,
                "message": commit_message
            }
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        return {"success": False, "error": f"GitHub API commit error ({e.code}): {error_body}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to commit to GitHub: {e}"}
