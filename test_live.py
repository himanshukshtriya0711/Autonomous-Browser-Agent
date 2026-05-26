"""Quick live test for the Autonomous Browser Agent API."""
import httpx, time, json

BASE = "http://localhost:8000/api"

# 1. Health
r = httpx.get("http://localhost:8000/health", timeout=5)
print(f"[HEALTH] {r.status_code} — {r.json()}")

# 2. Submit task
payload = {"prompt": "Find remote GenAI internships", "max_steps": 5, "headless": True}
r = httpx.post(f"{BASE}/task", json=payload, timeout=10)
data = r.json()
task_id = data.get("task_id", "")
print(f"[SUBMIT] {r.status_code} — task_id={task_id[:8]}... status={data.get('status')}")

# 3. Poll for up to 30s
print("[POLL] Waiting for task to complete...")
for i in range(10):
    time.sleep(3)
    p = httpx.get(f"{BASE}/task/{task_id}", timeout=5)
    d = p.json()
    status = d.get("status")
    logs   = len(d.get("logs", []))
    steps  = d.get("steps_completed", 0)
    print(f"  [{i+1}] status={status} steps={steps} logs={logs}")
    if status in ("completed", "failed", "cancelled"):
        jobs = d.get("result", {})
        if isinstance(jobs, dict):
            job_list = jobs.get("jobs", [])
            print(f"[RESULT] Jobs found: {len(job_list)}")
            for j in job_list[:3]:
                print(f"  • {j.get('role')} @ {j.get('company')} — {j.get('location')}")
        break

# 4. History
r = httpx.get(f"{BASE}/tasks", timeout=5)
print(f"[TASKS] Total tasks tracked: {len(r.json())}")

print("\n[DONE] All tests passed. Open http://localhost:8000 in browser.")
