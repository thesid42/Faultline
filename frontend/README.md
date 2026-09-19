# Faultline UI

Read-only React dashboard for persisted Faultline case files. It does not
fabricate incidents or execute mutations. Start the local API from the
repository root, then run the frontend:

```powershell
python -m faultline.api --db results/llama-live-validation.sqlite3
cd frontend
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8765`. The dashboard polls the case
list and selected raw `CaseFile` every four seconds. Investigation, approval,
export, and new-run actions remain CLI/review-workflow operations.

```powershell
npm run build
npm run lint
```
