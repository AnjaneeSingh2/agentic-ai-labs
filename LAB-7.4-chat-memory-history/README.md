# LAB 7.4 scripts – Chat Memory & Chat History

Run these in **OCI Cloud Shell**. They match Steps 9–13 and the Rollback section of the wiki page [LAB 7.4 ‐ Chat Memory & Chat History for the Multi‐Agent Console](https://github.com/AnjaneeSingh2/agentic-ai-labs/wiki/LAB-7.4-%E2%80%90-Chat-Memory-&-Chat-History-for-the-Multi%E2%80%90Agent-Console).

| File | What it is |
|---|---|
| `index.html` | The new Agent Console page with the chat history sidebar |
| `deploy-web-func.sh` | Backs up and swaps `~/WEB-FUNC/index.html`, checks disk space, logs in to OCIR, runs `fn deploy --app WEB-APP` |
| `cleanup-cloudshell-images.sh` | Frees Cloud Shell disk space. Removes untagged images and asks before removing each local image copy |
| `rollback-web-func.sh` | Restores a backed-up `index.html` and redeploys |

## Steps

1. Open Cloud Shell, then **Menu → Upload** and upload all four files.
2. If disk space is low:
   ```bash
   bash cleanup-cloudshell-images.sh
   ```
3. Deploy:
   ```bash
   bash deploy-web-func.sh ~/index.html
   ```
   Enter your **OCI auth token** when Docker asks for a password.
4. Open `https://ociagent.anjaneesinghpro.website/multi-agent/` and press **Ctrl+F5**.

## Rollback

```bash
bash rollback-web-func.sh                          # list backups
bash rollback-web-func.sh index.html.bak-<stamp>   # restore one and redeploy
```

## Settings

Override these with environment variables if your setup differs: `FUNC_DIR` (default `~/WEB-FUNC`), `APP` (default `WEB-APP`), `REGISTRY` (default `iad.ocir.io`), `OCIR_USER` (default `<namespace>/<your user>`), `MIN_FREE_MB` (default `1200`).
