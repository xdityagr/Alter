from __future__ import annotations

import time
import httpx
from typing import Any

# Client ID for GitHub CLI (publicly known)
# We use this because it has the right permissions and is trusted.
CLIENT_ID = "178c6fc778ccc68e1d6a"
SCOPES = "read:user"

def authenticate_device_flow() -> str:
    """
    Performs the GitHub Device Authorization Flow.
    Returns the access_token.
    """
    print("Initiating GitHub Device Flow...")
    
    with httpx.Client() as client:
        # 1. Request device code
        resp = client.post(
            "https://github.com/login/device/code",
            data={"client_id": CLIENT_ID, "scope": SCOPES},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        
        device_code = data["device_code"]
        user_code = data["user_code"]
        verification_uri = data["verification_uri"]
        interval = int(data.get("interval", 5))
        expires_in = int(data.get("expires_in", 900))
        
        print(f"\nPlease visit: {verification_uri}")
        print(f"And enter code: {user_code}\n")
        print(f"Copy/Paste: {user_code}")
        
        # 2. Poll for token
        start_time = time.time()
        while True:
            if time.time() - start_time > expires_in:
                raise RuntimeError("Authentication timed out.")
            
            time.sleep(interval)
            
            poll_resp = client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": CLIENT_ID, 
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
                },
                headers={"Accept": "application/json"},
            )
            
            if poll_resp.status_code == 200:
                token_data = poll_resp.json()
                if "access_token" in token_data:
                    print("\nSuccessfully authenticated!")
                    return token_data["access_token"]
                
                error = token_data.get("error")
                if error == "authorization_pending":
                    continue
                elif error == "slow_down":
                    interval += 5
                    continue
                elif error == "expired_token":
                    raise RuntimeError("Token expired. Please try again.")
                elif error == "access_denied":
                    raise RuntimeError("Access denied by user.")
                else:
                    # Some other error?
                    pass
