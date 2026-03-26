#!/usr/bin/env python3
"""
wait-for-workflow.py - Poll remote workflow with automatic GitHub App token refresh

This script monitors a GitHub Actions workflow run in a remote repository,
automatically refreshing the GitHub App installation token before expiration
to support workflows that run longer than the 60-minute token lifetime.

Environment Variables:
- GITHUB_APP_ID: GitHub App ID for authentication
- GITHUB_APP_PRIVATE_KEY: GitHub App private key (PEM format)
- GH_TOKEN: (Optional) Initial GitHub App installation token
- INITIAL_TOKEN_CREATED_AT: (Optional) ISO 8601 timestamp when GH_TOKEN was created
- REPOSITORY: Target repository (format: owner/repo)
- WORKFLOW_RUN_ID: Workflow run ID to monitor

Configuration:
- Max wait time: 360 minutes (6 hours)
- Poll interval: 120 seconds (2 minutes)

Outputs (written to $GITHUB_OUTPUT):
- run_id: Workflow run ID
- status: Final status (success, failure, skipped)
- url: URL to the workflow run

Exit Codes:
- 0: Workflow completed successfully
- 1: Workflow failed, was cancelled, or timed out
"""

import os
import sys
import time
import json
import subprocess
from typing import Tuple, Optional

# Import the token manager from the same directory
import importlib.util
spec = importlib.util.spec_from_file_location(
    "github_app_token_manager",
    os.path.join(os.path.dirname(__file__), "github_app_token_manager.py")
)
token_manager_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(token_manager_module)
GitHubAppTokenManager = token_manager_module.GitHubAppTokenManager


def check_workflow_status(run_id: str, token: str, repo: str) -> Tuple[str, Optional[str]]:
    """
    Check the status of a workflow run.

    Args:
        run_id: Workflow run ID
        token: GitHub API token
        repo: Repository (format: owner/repo)

    Returns:
        Tuple of (status, conclusion)
        - status: queued, in_progress, completed
        - conclusion: success, failure, cancelled, etc. (None if not completed)
    """
    env = os.environ.copy()
    env["GH_TOKEN"] = token

    result = subprocess.run(
        [
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
            f"/repos/{repo}/actions/runs/{run_id}",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    data = json.loads(result.stdout)
    status = data["status"]
    conclusion = data.get("conclusion")

    return status, conclusion


def write_output(key: str, value: str) -> None:
    """Write key=value pair to $GITHUB_OUTPUT file."""
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"{key}={value}\n")


def main() -> int:
    """
    Main function to poll workflow with automatic token refresh.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    print("⏳ Monitoring workflow with automatic token refresh", flush=True)
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)

    # Configuration
    max_wait_minutes = 360  # 6 hours
    poll_interval = 120  # 2 minutes

    try:
        app_id = os.environ["GITHUB_APP_ID"]
        private_key = os.environ["GITHUB_APP_PRIVATE_KEY"]
        initial_token = os.environ.get("GH_TOKEN")
        initial_token_created_at = os.environ.get("INITIAL_TOKEN_CREATED_AT")
        repository = os.environ["REPOSITORY"]
        run_id = os.environ["WORKFLOW_RUN_ID"]
    except KeyError as e:
        print(f"❌ Missing required environment variable: {e}", file=sys.stderr, flush=True)
        return 1

    try:
        owner, repo_name = repository.split("/")
    except ValueError:
        print(f"❌ Invalid repository format: {repository} (expected: owner/repo)", file=sys.stderr, flush=True)
        return 1

    run_url = f"https://github.com/{repository}/actions/runs/{run_id}"

    print(f"🔗 {run_url}", flush=True)
    print(f"⏰ Max wait: {max_wait_minutes}m | Poll: {poll_interval}s | Token refresh: 55m", flush=True)
    print("", flush=True)

    token_manager = GitHubAppTokenManager(
        app_id, private_key, owner, repo_name, initial_token, initial_token_created_at
    )

    start_time = time.time()
    max_wait_seconds = max_wait_minutes * 60

    try:
        while time.time() - start_time < max_wait_seconds:
            token = token_manager.get_token()
            status, conclusion = check_workflow_status(run_id, token, repository)

            elapsed_seconds = int(time.time() - start_time)
            elapsed_minutes = elapsed_seconds // 60
            conclusion_display = conclusion if conclusion else "N/A"

            print(f"[{elapsed_minutes}m] Status: {status}, Conclusion: {conclusion_display}", flush=True)

            if status == "completed":
                print("", flush=True)
                print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)

                write_output("run_id", run_id)
                write_output("url", run_url)

                if conclusion == "success":
                    print("✅ Workflow completed successfully!", flush=True)
                    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)
                    write_output("status", "success")
                    return 0
                elif conclusion == "skipped":
                    print("⏭️  Workflow was skipped", flush=True)
                    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)
                    write_output("status", "skipped")
                    return 1
                else:
                    print(f"❌ Workflow completed with status: {conclusion}", flush=True)
                    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)
                    write_output("status", "failure")
                    return 1

            time.sleep(poll_interval)

        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)
        print(f"⏰ Timeout after {max_wait_minutes}m - workflow still running: {run_url}", flush=True)
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)
        write_output("run_id", run_id)
        write_output("url", run_url)
        write_output("status", "failure")
        return 1

    except subprocess.CalledProcessError as e:
        print(f"❌ API call failed: {e}", file=sys.stderr, flush=True)
        if hasattr(e, "stderr") and e.stderr:
            print(f"   stderr: {e.stderr}", file=sys.stderr, flush=True)
        write_output("run_id", run_id)
        write_output("url", run_url)
        write_output("status", "failure")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        write_output("run_id", run_id)
        write_output("url", run_url)
        write_output("status", "failure")
        return 1


if __name__ == "__main__":
    sys.exit(main())

