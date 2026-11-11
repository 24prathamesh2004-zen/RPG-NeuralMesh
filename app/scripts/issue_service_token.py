"""Print a development service token for a registered application (config/applications/<id>.yaml).

    python -m scripts.issue_service_token              # SkillForge, 12 hours
    python -m scripts.issue_service_token snapscore    # Snap and Score

Development only: signed with the shared POC secret, like every token of this POC. The token carries the
application's identity and roles from its registry file, and NeuralMesh checks every call against that file.
"""
from __future__ import annotations

import sys

from api.auth import issue_poc_token
from services.applications import applications
from shared.config import get_settings

if get_settings().app_env != "development":
    sys.exit("Service tokens are issued by this script in development only.")
app_id = sys.argv[1] if len(sys.argv) > 1 else "skillforge"
app = applications().get(app_id)
if app is None:
    sys.exit(f"No application {app_id}. Registered: {', '.join(sorted(applications()))}")
print(issue_poc_token({"sub": app.identity, "company": "group", "roles": list(app.token_roles), "scope": "neuralmesh.context"}))
