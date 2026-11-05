"""Print a development service token for SkillForge's calls to /api/v1/context.

    python -m scripts.issue_service_token            # context_client and talent_exporter, 12 hours

Development only: signed with the shared POC secret, like every token of this POC.
"""
from __future__ import annotations

import sys

from api.auth import issue_poc_token
from shared.config import get_settings

if get_settings().app_env != "development":
    sys.exit("Service tokens are issued by this script in development only.")
print(issue_poc_token({"sub": "svc:skillforge", "company": "group", "roles": ["context_client", "talent_exporter"],
                       "scope": "neuralmesh.context"}))
