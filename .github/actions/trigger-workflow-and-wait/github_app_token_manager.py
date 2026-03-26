#!/usr/bin/env python3
"""
GitHub App Token Manager - Automatic token refresh for long-running workflows

This module provides a token manager that automatically refreshes GitHub App
installation tokens before they expire, enabling monitoring of workflows that
run longer than the 60-minute token lifetime.
"""

import os
import sys
import time
import json
import subprocess
import tempfile
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional


class GitHubAppTokenManager:
    """Manages GitHub App installation token lifecycle with automatic refresh."""

    TOKEN_REFRESH_INTERVAL = timedelta(minutes=55)  # 5-minute safety buffer before 60-min expiry

    def __init__(
        self,
        app_id: str,
        private_key: str,
        owner: str,
        repo: str,
        initial_token: Optional[str] = None,
        initial_token_created_at: Optional[str] = None,
    ):
        """Initialize token manager."""
        self.app_id = str(app_id)
        self.private_key = private_key
        self.owner = owner
        self.repo = repo

        if initial_token:
            if not initial_token_created_at:
                raise ValueError("initial_token_created_at must be provided when initial_token is set")

            self.token = initial_token
            created_at = datetime.fromisoformat(initial_token_created_at.replace("Z", "+00:00"))
            self.token_expires_at = created_at + self.TOKEN_REFRESH_INTERVAL
            expires_str = self.token_expires_at.strftime("%H:%M:%S UTC")
            print(f"✅ Using initial installation token (will refresh at {expires_str})", flush=True)
        else:
            self.token = None
            self.token_expires_at = None

    def get_token(self) -> str:
        """Get a valid installation token, refreshing if necessary."""
        if not self.token or (self.token_expires_at and datetime.now(timezone.utc) >= self.token_expires_at):
            self._refresh_token()
        return self.token

    def _refresh_token(self) -> None:
        """Generate a new GitHub App installation token."""
        print("🔄 Refreshing token...", flush=True)

        key_file = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".pem") as f:
                key_file = f.name
                f.write(self.private_key)

            os.chmod(key_file, 0o400)

            installation_id = self._get_installation_id(key_file)
            token_data = self._get_installation_token(key_file, installation_id)

            self.token = token_data["token"]
            self.token_expires_at = datetime.now(timezone.utc) + self.TOKEN_REFRESH_INTERVAL

            print(
                f"✅ Token refreshed successfully (valid until {self.token_expires_at.strftime('%H:%M:%S UTC')})",
                flush=True,
            )

        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to refresh token: {e}", file=sys.stderr, flush=True)
            if hasattr(e, "stderr") and e.stderr:
                print(f"   stderr: {e.stderr}", file=sys.stderr, flush=True)
            raise
        except Exception as e:
            print(f"❌ Unexpected error during token refresh: {e}", file=sys.stderr, flush=True)
            raise
        finally:
            if key_file and os.path.exists(key_file):
                os.unlink(key_file)

    def _generate_jwt_token(self, key_file: str) -> str:
        """Generate GitHub App JWT token."""
        try:
            import jwt

            now = int(time.time())
            payload = {
                "iat": now - 60,
                "exp": now + 600,
                "iss": str(self.app_id),
            }

            with open(key_file, "r") as f:
                private_key = f.read()

            token = jwt.encode(payload, private_key, algorithm="RS256")

            if isinstance(token, bytes):
                token = token.decode("utf-8")

            return token

        except ImportError:
            print("ℹ️  PyJWT not available, using manual JWT generation", flush=True)
            return self._generate_jwt_manual(key_file)
        except Exception as e:
            print(f"⚠️  PyJWT failed ({e}), falling back to manual JWT generation", flush=True)
            return self._generate_jwt_manual(key_file)

    def _generate_jwt_manual(self, key_file: str) -> str:
        """Manually generate JWT using openssl (fallback when PyJWT unavailable)."""
        header = {"alg": "RS256", "typ": "JWT"}

        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 600,
            "iss": str(self.app_id),
        }

        header_json = json.dumps(header, separators=(",", ":"))
        payload_json = json.dumps(payload, separators=(",", ":"))

        header_b64 = base64.urlsafe_b64encode(header_json.encode()).decode().rstrip("=")
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")

        message = f"{header_b64}.{payload_b64}"

        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_file, "-binary"],
            input=message.encode(),
            capture_output=True,
            check=True,
        )

        signature_b64 = base64.urlsafe_b64encode(result.stdout).decode().rstrip("=")

        return f"{message}.{signature_b64}"

    def _get_installation_id(self, key_file: str) -> str:
        """Get GitHub App installation ID for the target repository."""
        jwt_token = self._generate_jwt_token(key_file)

        result = subprocess.run(
            [
                "curl",
                "-s",
                "-f",
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                f"Authorization: Bearer {jwt_token}",
                "-H",
                "X-GitHub-Api-Version: 2022-11-28",
                f"https://api.github.com/repos/{self.owner}/{self.repo}/installation",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        data = json.loads(result.stdout)
        return str(data["id"])

    def _get_installation_token(self, key_file: str, installation_id: str) -> dict:
        """Exchange JWT for installation access token."""
        jwt_token = self._generate_jwt_token(key_file)

        request_body = json.dumps({"repositories": [self.repo]})

        result = subprocess.run(
            [
                "curl",
                "-s",
                "-f",
                "-X",
                "POST",
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                f"Authorization: Bearer {jwt_token}",
                "-H",
                "X-GitHub-Api-Version: 2022-11-28",
                "-H",
                "Content-Type: application/json",
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                "-d",
                request_body,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        return json.loads(result.stdout)

