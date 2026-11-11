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

## Sample inputs for the Context graph page

`presenter@neuralmesh.local` is the one mesh admin of these accounts, so it is the account that uploads inputs and
sees every uploaded input. An uploaded input belongs to a company and a context graph, not to the account that
uploaded it, so a second admin account would show the same list. To fill the page the way it looks after three months
of use, load the ten synthetic sample inputs from `app`, with the stack running:

```
python -m scripts.sample_inputs load        # ten inputs in four context graphs, one of them a removed draft
python -m scripts.sample_inputs status      # what is loaded, and which other uploads exist
python -m scripts.sample_inputs remove      # takes the sample inputs out again, after a question
```

The files and their list are in `neuralmesh_kb_pack/sample_inputs`, with a README. `remove` leaves every input that a
person added. To see what a company account sees, sign in as `kec.expert` (3 of the sample inputs), `ceat.expert` (5)
or `harrisons.expert` (3): each sees the inputs of its own company and the two shared ones.
