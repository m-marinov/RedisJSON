#!/bin/bash
set -euo pipefail

# Generic workflow trigger script
# Triggers a workflow in a remote repository using workflow_dispatch API

# Validate required environment variables
: "${GH_TOKEN:?Error: GH_TOKEN is not set}"
: "${REPOSITORY:?Error: REPOSITORY is not set}"
: "${WORKFLOW_FILE:?Error: WORKFLOW_FILE is not set}"
: "${WORKFLOW_REF:?Error: WORKFLOW_REF is not set}"
: "${WORKFLOW_INPUTS:?Error: WORKFLOW_INPUTS is not set}"

echo "🚀 Triggering workflow in ${REPOSITORY}"
echo "   Workflow: ${WORKFLOW_FILE}"
echo "   Ref: ${WORKFLOW_REF}"
echo "   Inputs: ${WORKFLOW_INPUTS}"

# Prepare the workflow dispatch request body
# Using return_run_details: true to get run ID and URL directly from the response
# See: https://github.blog/changelog/2026-02-19-workflow-dispatch-api-now-returns-run-ids/
REQUEST_BODY=$(jq -n \
  --arg ref "${WORKFLOW_REF}" \
  --argjson inputs "${WORKFLOW_INPUTS}" \
  '{
    ref: $ref,
    inputs: $inputs,
    return_run_details: true
  }')

# Trigger the workflow using GitHub CLI and capture the response
DISPATCH_RESPONSE=$(gh api \
  --method POST \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "/repos/${REPOSITORY}/actions/workflows/${WORKFLOW_FILE}/dispatches" \
  --input - <<< "${REQUEST_BODY}") || {
  echo "❌ Failed to trigger workflow"
  exit 1
}

# Extract run details from the API response
RUN_ID=$(echo "${DISPATCH_RESPONSE}" | jq -r '.workflow_run_id // empty' 2>/dev/null || echo "")
RUN_URL=$(echo "${DISPATCH_RESPONSE}" | jq -r '.html_url // empty' 2>/dev/null || echo "")

# Validate that we received both run ID and URL
if [[ -z "${RUN_ID}" ]] || [[ -z "${RUN_URL}" ]]; then
  echo "❌ Failed to extract workflow run details from API response"
  echo "ℹ️  Response: ${DISPATCH_RESPONSE}"
  echo "ℹ️  Check manually: https://github.com/${REPOSITORY}/actions/workflows/${WORKFLOW_FILE}"
  exit 1
fi

echo "✅ Workflow triggered: ${RUN_URL}"

# Set outputs for the next step
echo "run_id=${RUN_ID}" >> $GITHUB_OUTPUT
echo "run_url=${RUN_URL}" >> $GITHUB_OUTPUT
