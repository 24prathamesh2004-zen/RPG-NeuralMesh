# Presentation accounts

Seed synthetic accounts and a small approval activity set from the `app`
directory:

```powershell
..\venv\Scripts\python.exe -m scripts.seed_demo_accounts
```

The command is allowed only with `APP_ENV=development`. It only writes accounts
at the reserved `@neuralmesh.local` domain, opts four synthetic subsidiary
experts into the directory, and creates one pending KEC content request plus
one CEAT expert-introduction request. Re-running resets only those demo
passwords and does not create duplicate pending requests.

All accounts use the shared presentation password `MeshPilot!2026`:

| Email | Subsidiary | Profile |
|---|---|---|
| `presenter@neuralmesh.local` | Zensar | Group presenter; pending approvals requester |
| `ceat.expert@neuralmesh.local` | CEAT | Opted-in raw-material quality expert |
| `kec.expert@neuralmesh.local` | KEC International | Opted-in integration expert |
| `zensar.expert@neuralmesh.local` | Zensar | Opted-in AI delivery expert |
| `harrisons.expert@neuralmesh.local` | Harrisons Malayalam | Opted-in estate operations expert |

The sign-in screen offers one-click account filling in Vite development mode.
These are synthetic local POC accounts, not production credentials.

For an Ask demo, keep the CEAT and Harrisons nodes running on ports `8101` and
`8104`. Start each from `app` in its own terminal with:

```powershell
..\venv\Scripts\python.exe -m mcp_nodes.ceat
..\venv\Scripts\python.exe -m mcp_nodes.kec
..\venv\Scripts\python.exe -m mcp_nodes.zensar
..\venv\Scripts\python.exe -m mcp_nodes.harrisons
```

The prepared Ask example compares CEAT materials-handling knowledge with
Harrisons latex-spoilage trends. All content is synthetic.