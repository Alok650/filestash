import requests
import time
import sys
import os

BASE_URL = "http://localhost:8000/api"
ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "my-super-secret-admin-key")

def print_header(msg):
    print(f"\n{'='*20} {msg} {'='*20}")

def test_anonymous_rate_limit():
    print_header("Testing Anonymous Rate Limit (2/sec)")
    for i in range(5):
        resp = requests.get(f"{BASE_URL}/files/")
        print(f"Req {i+1}: {resp.status_code} " + (f"({resp.json().get('error')})" if resp.status_code == 429 else ""))
        if resp.status_code == 429:
            print("✓ Successfully triggered 429 Too Many Requests")
            break
        time.sleep(0.1)

def create_test_key(label, quota_bytes=1024):
    print_header(f"Creating Test Key with {quota_bytes} bytes quota")
    headers = {"Authorization": f"ApiKey {ADMIN_KEY}"}
    payload = {"label": label, "storage_quota_bytes": quota_bytes}
    resp = requests.post(f"{BASE_URL}/keys/", json=payload, headers=headers)
    if resp.status_code == 201:
        key_data = resp.json()
        print(f"✓ Key Created: {key_data['key']}")
        return key_data['key']
    else:
        print(f"✗ Failed to create key: {resp.text}")
        return None

def test_authenticated_rate_limit(api_key):
    print_header("Testing Authenticated Rate Limit (10/sec)")
    headers = {"Authorization": f"ApiKey {api_key}"}
    for i in range(15):
        resp = requests.get(f"{BASE_URL}/files/", headers=headers)
        print(f"Req {i+1}: {resp.status_code} " + (f"({resp.json().get('error')})" if resp.status_code == 429 else ""))
        if resp.status_code == 429:
            print("✓ Successfully triggered 429 Too Many Requests")
            break

def test_storage_quota(api_key):
    print_header("Testing Storage Quota (1024 bytes)")
    headers = {"Authorization": f"ApiKey {api_key}"}
    
    file_content = b"x" * 600
    for i in range(5):
        files = {'file': ('test.txt', file_content, 'text/plain')}
        resp = requests.post(f"{BASE_URL}/files/", headers=headers, files=files)
        if resp.status_code == 201:
            print(f"Upload {i+1}: Success (201)")
        elif resp.status_code == 413:
            print(f"Upload {i+1}: 413 Payload Too Large (✓ Quota Exceeded)")
            print(f"Response: {resp.json()}")
            break
        else:
            print(f"Upload {i+1}: Error {resp.status_code} - {resp.text}")

if __name__ == "__main__":
    if not ADMIN_KEY:
        print("Error: Please set ADMIN_API_KEY environment variable")
        sys.exit(1)

    try:
        requests.get(BASE_URL)
    except:
        print(f"Error: Server not found at {BASE_URL}. Run 'make run' first.")
        sys.exit(1)

    test_anonymous_rate_limit()
    time.sleep(1.1)

    test_key = create_test_key("Rate Limit Test Key", quota_bytes=1000)
    if test_key:
        test_authenticated_rate_limit(test_key)
        print("\nWaiting for rate limit to reset before testing quota...")
        time.sleep(1.1)
        test_storage_quota(test_key)
