# Faultline UI

React dashboard for persisted Faultline case files with a bounded launch
dialog. It does not fabricate incidents or expose arbitrary mutations. The
simulated mode is the default; live mode is explicit, backend-configured, and
subject to the server's existing limits. Approvals and exports remain CLI or
review-workflow operations. Keep API credentials in the repository `.env`
only; they stay backend-side and `.env.example` is the safe template.
Start the local API from the repository root using the existing `.venv`, then
run the frontend:

```powershell
.\.venv\Scripts\python.exe -m faultline.api --db results/llama-live-validation.sqlite3
cd frontend
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8765`. The dashboard polls the case
list and selected raw `CaseFile` every four seconds. New investigations use
the backend-advertised profile/mode capabilities and are queued through the
bounded launch dialog; the browser never receives provider credentials.

```powershell
npm run build
npm run lint
```
