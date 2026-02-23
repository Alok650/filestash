import requests
import os
import sys
import time

BASE_URL = "http://localhost:8000/api"
ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "my-super-secret-admin-key")

def print_step(msg):
    print(f"\n=== {msg} ===")

def create_key(label):
    headers = {"Authorization": f"ApiKey {ADMIN_KEY}"}
    resp = requests.post(f"{BASE_URL}/keys/", json={"label": label}, headers=headers)
    if resp.status_code != 201:
        print(f"Error creating key: {resp.text}")
        sys.exit(1)
    return resp.json()['key']

def upload_file(key, name, mime, content=b"test"):
    headers = {"Authorization": f"ApiKey {key}"}
    files = {'file': (name, content, mime)}
    resp = requests.post(f"{BASE_URL}/files/", headers=headers, files=files)
    return resp

def test_search_and_visibility():
    print_step("Setup: Creating two different API Keys")
    key_a = create_key("User A")
    key_b = create_key("User B")
    
    print_step("Testing Data Isolation")
    upload_file(key_a, "private_a.txt", "text/plain")
    upload_file(key_b, "private_b.txt", "text/plain")
    
    resp_a = requests.get(f"{BASE_URL}/files/", headers={"Authorization": f"ApiKey {key_a}"})
    files_a = [f['original_filename'] for f in resp_a.json()['results']]
    print(f"User A sees: {files_a}")
    if "private_b.txt" not in files_a:
        print("✓ SUCCESS: User A cannot see User B's files.")
    
    print_step("Testing Admin Visibility")
    resp_admin = requests.get(f"{BASE_URL}/files/", headers={"Authorization": f"ApiKey {ADMIN_KEY}"})
    print(f"Admin sees {resp_admin.json()['count']} total files")
    files_admin = [f['original_filename'] for f in resp_admin.json()['results']]
    if "private_a.txt" in files_admin and "private_b.txt" in files_admin:
        print("✓ SUCCESS: Admin can see files from both users.")

    print_step("Testing Search (?search=)")
    upload_file(key_a, "report_january.pdf", "application/pdf")
    upload_file(key_a, "invoice_july.pdf", "application/pdf")
    
    search_resp = requests.get(f"{BASE_URL}/files/?search=report", headers={"Authorization": f"ApiKey {key_a}"})
    search_results = [f['original_filename'] for f in search_resp.json()['results']]
    print(f"Search 'report' results: {search_results}")
    if len(search_results) == 1 and "report_january.pdf" in search_results:
        print("✓ SUCCESS: Search filter works correctly.")

    print_step("Testing File Type Prefix (?file_type=image/)")
    upload_file(key_a, "photo.png", "image/png")
    upload_file(key_a, "icon.jpg", "image/jpeg")
    
    prefix_resp = requests.get(f"{BASE_URL}/files/?file_type=image/", headers={"Authorization": f"ApiKey {key_a}"})
    prefix_results = [f['original_filename'] for f in prefix_resp.json()['results']]
    print(f"Prefix 'image/' results: {prefix_results}")
    if len(prefix_results) >= 2:
        print("✓ SUCCESS: Prefix matching (trailing slash) works.")

    print_step("Testing Blocked File Types (Security)")
    blocked_resp = upload_file(key_a, "malicious.html", "text/html", content=b"<h1>Hacked</h1>")
    print(f"Status for text/html: {blocked_resp.status_code}")
    if blocked_resp.status_code == 415:
        print("✓ SUCCESS: System correctly blocked restricted file type (415 Unsupported Media Type).")

    time.sleep(1.1)

    print_step("Testing Metadata Updates (PATCH)")
    upload_resp = upload_file(key_a, "old_name.txt", "text/plain")
    file_id = upload_resp.json()['id']
    
    patch_resp = requests.patch(
        f"{BASE_URL}/files/{file_id}/", 
        json={"original_filename": "new_name.txt"}, 
        headers={"Authorization": f"ApiKey {key_a}"}
    )
    
    if patch_resp.status_code == 200:
        new_name = patch_resp.json().get('original_filename')
        if new_name == "new_name.txt":
            print("✓ SUCCESS: Filename successfully updated via PATCH.")
        else:
            print(f"✗ FAILURE: Filename was not updated. Got: {new_name}")
    else:
        print(f"✗ FAILURE: PATCH request failed with {patch_resp.status_code}: {patch_resp.text}")

    time.sleep(1.1)

    print_step("Testing Date Range Filtering")
    now = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()) + 'Z'
    print(f"Filtering files uploaded after: {now}")
    
    time.sleep(1.2)
    upload_file(key_a, "truly_recent.txt", "text/plain")
    
    date_resp = requests.get(f"{BASE_URL}/files/?uploaded_after={now}", headers={"Authorization": f"ApiKey {key_a}"})
    date_results = [f['original_filename'] for f in date_resp.json()['results']]
    print(f"Search results: {date_results}")
    
    if "truly_recent.txt" in date_results and "private_a.txt" not in date_results:
        print("✓ SUCCESS: Date filtering correctly isolates recent uploads.")
    else:
        print("✗ FAILURE: Date filtering results were unexpected.")

if __name__ == "__main__":
    test_search_and_visibility()
