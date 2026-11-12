"""Many inputs at once: a zip or a folder becomes one context graph for each subfolder, a check keeps nothing, a file
that cannot be read is refused alone, the list file names topics and titles, and a zip cannot leave its folder."""
from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from api.main import app
from services import upload_batch
from tests.test_uploads import ADMIN, DATA, _headers, mesh  # noqa: F401 - mesh is the fixture

URL = "/api/v1/mesh/uploads/batch"
LEAVE = "Leave policy for the plant. Rubber storage lots are issued first in, first out, and leave is approved by the shift lead every week."
ATTEND = "Attendance questions and answers. The shift roster is kept by the supervisor, and a late arrival is recorded on the same day."
JOIN = "Joining day steps. The new person gets a laptop request, an access card and a safety briefing on the first morning at the plant."


def _zip(files: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buffer.getvalue()


def _send(client, files, check=False, headers=ADMIN, paths=None, **fields):
    data = {"node_id": "ceat", "datapoint": "E-02", "check": "true" if check else "false", **fields}
    if paths:
        data["paths"] = paths
    return client.post(URL, data=data, files=[("files", (name, content, "application/octet-stream")) for name, content in files], headers=headers)


def _count() -> int:
    return len(list((DATA / "ceat" / "contributions").glob("*.json")))


def test_a_zip_of_a_folder_is_checked_then_kept_as_one_graph_for_each_subfolder(mesh):
    client = TestClient(app)
    packed = _zip({"onboarding_buddy/leave_and_attendance/leave_policy.txt": LEAVE, "onboarding_buddy/leave_and_attendance/attendance_faq.md": ATTEND,
                   "onboarding_buddy/first_week/joining_day.txt": JOIN, "onboarding_buddy/notes.xlsx": b"not read",
                   "onboarding_buddy/first_week/copy_of_joining_day.txt": JOIN, "onboarding_buddy/.DS_Store": b"x", "__MACOSX/onboarding_buddy/._x": b"x"})
    assert _send(client, [("onboarding_buddy.zip", packed)], check=True, headers=_headers("ceat")).status_code == 403
    before = _count()
    checked = _send(client, [("onboarding_buddy.zip", packed)], check=True)
    assert checked.status_code == 200, checked.text
    plan = checked.json()
    assert plan["checked_only"] and plan["name"] == "Onboarding buddy" and plan["ok"] == 3 and plan["refused"] == 2 and _count() == before
    assert {(g["name"], g["files"], g["new"]) for g in plan["graphs"]} == {("Leave and attendance", 2, True), ("First week", 1, True)}
    reasons = {e["path"]: e["reason"] for e in plan["entries"] if e["status"] == "refused"}
    assert ".xlsx is not read" in reasons["notes.xlsx"] and reasons["first_week/joining_day.txt"] == "The same file as first_week/copy_of_joining_day.txt."
    assert all("data" not in e for e in plan["entries"])
    kept = _send(client, [("onboarding_buddy.zip", packed)])
    assert kept.status_code == 200, kept.text
    body = kept.json()
    assert len(body["saved"]) == 3 and len(body["refused"]) == 2 and _count() == before + 3 and body["refresh"]["ceat"].startswith("loaded")
    by_graph = {g["name"]: g for g in body["graphs"]}
    assert by_graph["Leave and attendance"]["files"] == 2 and by_graph["First week"]["files"] == 1
    listed = client.get("/api/v1/mesh/uploads", headers=ADMIN).json()
    leave = next(g for g in listed["graphs"] if g["name"] == "Leave and attendance")
    assert leave["inputs"] == 2 and leave["id"] == by_graph["Leave and attendance"]["id"]
    assert client.get(f"/api/v1/mesh/uploads/graphs/{leave['id']}", headers=ADMIN).json()["documents"].__len__() == 2
    # the same zip again: every file is already an input, so nothing more is kept
    again = _send(client, [("onboarding_buddy.zip", packed)]).json()
    assert again["saved"] == [] and _count() == before + 3
    assert any('already an input of "Leave and attendance"' in e["reason"] for e in again["refused"])


def test_a_folder_sent_with_its_paths_and_a_list_file(mesh):
    client = TestClient(app)
    listing = ("file,topic,title,real_data,owner\n"
               "hr/leave.txt,Leave rules of the plant,Leave policy 2026,no,HR lead\n"
               "hr/missing.txt,Leave rules of the plant,,,\n")
    files = [("leave.txt", LEAVE + " Folder copy."), ("roster.txt", ATTEND + " Folder copy."), ("inputs.csv", listing)]
    paths = ["buddy/hr/leave.txt", "buddy/hr/roster.txt", "buddy/inputs.csv"]
    plan = _send(client, files, check=True, paths=paths).json()
    by_path = {e["path"]: e for e in plan["entries"]}
    assert set(by_path) == {"hr/leave.txt", "hr/roster.txt"}  # the list file is not an input
    assert by_path["hr/leave.txt"]["graph"] == "Leave rules of the plant" and by_path["hr/leave.txt"]["title"] == "Leave policy 2026" and by_path["hr/leave.txt"]["synthetic"] is True
    assert by_path["hr/roster.txt"]["graph"] == "Buddy hr" and by_path["hr/roster.txt"]["synthetic"] is False
    assert any("not read: owner" in n for n in plan["notes"]) and any("hr/missing.txt" in n for n in plan["notes"])
    body = _send(client, files, paths=paths).json()
    assert {r["document"]["title"] for r in body["saved"]} >= {"Leave policy 2026"} and {r["synthetic"] for r in body["saved"]} == {True, False}


def test_a_zip_cannot_leave_its_folder_and_the_limits_hold(mesh, monkeypatch):
    client = TestClient(app)
    plan = _send(client, [("x.zip", _zip({"../outside.txt": LEAVE, "/etc/passwd.txt": LEAVE, "inner.zip": _zip({"a.txt": LEAVE}), "ok/fine.txt": JOIN + " Limits."}))], check=True).json()
    reasons = {e["path"]: e.get("reason", "") for e in plan["entries"]}
    assert plan["ok"] == 1 and "leaves the folder" in reasons["../outside.txt"] and "leaves the folder" in reasons["/etc/passwd.txt"] and ".zip is not read" in reasons["inner.zip"]
    assert _send(client, [("x.zip", b"this is not a zip")], check=True).status_code == 422
    monkeypatch.setattr(upload_batch, "MAX_FILES", 2)
    many = _send(client, [("x.zip", _zip({f"t/{i}.txt": f"{JOIN} {i}" for i in range(3)}))], check=True)
    assert many.status_code == 422 and "At most 2" in many.json()["detail"]
    monkeypatch.setattr(upload_batch, "MAX_FILES", 100)
    monkeypatch.setattr(upload_batch.uploads, "MAX_BYTES", 50)
    big = _send(client, [("x.zip", _zip({"t/a.txt": JOIN}))], check=True).json()
    assert big["ok"] == 0 and "larger than" in big["entries"][0]["reason"]


def test_a_new_catalogue_item_a_graph_name_and_file_names_for_a_shared_heading(mesh):
    client = TestClient(app)
    head = "ZENSAR TECHNOLOGIES\n\n"
    packed = _zip({"Final_Knowledge/Employee_Knowledge.txt": head + LEAVE, "Final_Knowledge/Intern_Knowledge.txt": head + ATTEND, "Final_Knowledge/General_Knowledge.txt": head + JOIN})
    fields = {"datapoint": "new", "new_item_title": "Onboarding buddy knowledge", "new_item_area": "engineering", "graph_name": "Onboarding buddy"}
    assert _send(client, [("Final_Knowledge.zip", packed)], check=True, datapoint="new", new_item_title="ab", new_item_area="engineering").status_code == 422
    plan = _send(client, [("Final_Knowledge.zip", packed)], check=True, **fields).json()
    assert plan["ok"] == 3 and plan["name"] == "Final Knowledge" and plan["new_item"]["title"] == "Onboarding buddy knowledge"
    assert [g["name"] for g in plan["graphs"]] == ["Onboarding buddy"]
    assert {e["title"] for e in plan["entries"]} == {"Employee Knowledge", "Intern Knowledge", "General Knowledge"}  # not three times the heading
    before = len(list((DATA / "ceat" / "added_items").glob("*.json"))) if (DATA / "ceat" / "added_items").is_dir() else 0
    body = _send(client, [("Final_Knowledge.zip", packed)], **fields).json()
    assert len(body["saved"]) == 3 and body["refused"] == [] and body["new_item"]["title"] == "Onboarding buddy knowledge"
    assert len({r["document"]["datapoint"] for r in body["saved"]}) == 1 and body["saved"][0]["document"]["datapoint"] == f"ceat:{body['new_item']['code']}"
    assert len(list((DATA / "ceat" / "added_items").glob("*.json"))) == before + 1  # one item for the three files
    assert [g["name"] for g in body["graphs"]] == ["Onboarding buddy"] and body["graphs"][0]["files"] == 3
