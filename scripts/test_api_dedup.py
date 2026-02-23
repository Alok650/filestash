import requests
import os
import hashlib
import sys

BASE_URL = "http://localhost:8000/api"
ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "my-super-secret-admin-key")

def print_step(msg):
    print(f"\n--- {msg} ---")

def get_hash(content):
    return hashlib.sha256(content).hexdigest()

def handle_response(resp):
    if resp.status_code >= 400:
        print(f"✗ Server returned error {resp.status_code}")
        print(f"Response Body: {resp.text}")
        sys.exit(1)
    try:
        return resp.json()
    except Exception as e:
        print(f"✗ Failed to decode JSON from response. Status: {resp.status_code}")
        print(f"Response Text: {resp.text}")
        sys.exit(1)

def test_deduplication_and_cleanup():
    print_step("Checking server connectivity")
    try:
        requests.get(f"{BASE_URL}/files/")
    except requests.exceptions.ConnectionError:
        print(f"✗ Error: Could not connect to server at {BASE_URL}")
        return

    print_step("Creating working API Key")
    admin_headers = {"Authorization": f"ApiKey {ADMIN_KEY}"}
    resp = requests.post(f"{BASE_URL}/keys/", json={"label": "Cleanup Test"}, headers=admin_headers)
    
    key_data = handle_response(resp)
    auth_key = key_data['key']
    headers = {"Authorization": f"ApiKey {auth_key}"}
    
    print_step("Uploading File #1 (Original)")
    content = b"Deduplication test content " + os.urandom(8)
    files = {'file': ('file1.txt', content, 'text/plain')}
    r1 = requests.post(f"{BASE_URL}/files/", headers=headers, files=files)
    
    data1 = handle_response(r1)
    id1 = data1['id']
    storage_path1 = data1['file']

    print_step("Uploading File #2 (Duplicate)")
    files = {'file': ('file2_copy.txt', content, 'text/plain')}
    r2 = requests.post(f"{BASE_URL}/files/", headers=headers, files=files)
    
    data2 = handle_response(r2)
    id2 = data2['id']
    storage_path2 = data2['file']

    if storage_path1 == storage_path2:
        print("✓ SUCCESS: Physical files are shared.")
    else:
        print("✗ FAILURE: Physical files were not shared.")

    print_step(f"Checking duplicates endpoint")
    dup_resp = requests.get(f"{BASE_URL}/files/{id1}/duplicates/", headers=headers)
    duplicates = handle_response(dup_resp)
    if len(duplicates) > 0 and duplicates[0]['id'] == id2:
        print("✓ SUCCESS: File 2 identified as a duplicate.")

    print_step("Deleting File 1")
    requests.delete(f"{BASE_URL}/files/{id1}/", headers=headers)
    
    check_r2 = requests.get(f"{BASE_URL}/files/{id2}/", headers=headers)
    if check_r2.status_code == 200:
        print("✓ SUCCESS: File 2 record remains.")
    
    print_step("Deleting File 2")
    requests.delete(f"{BASE_URL}/files/{id2}/", headers=headers)
    print("✓ Done.")

if __name__ == "__main__":
    test_deduplication_and_cleanup()
