#!/usr/bin/env python3
import base64
import csv
import io
import json
import os
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from clone_jira import (
    JiraClient,
    build_payload,
    get_component_names,
    load_config,
    load_dotenv,
    resolve_clone_fields,
)


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
CONFIG_PATH = ROOT / "clone-config.json"
ENV_PATH = ROOT / ".env"


def parse_tickets(value):
    tickets = []
    for raw in value.replace(",", "\n").splitlines():
        ticket = raw.strip()
        if ticket and not ticket.startswith("#"):
            tickets.append(ticket)
    return tickets


def normalize_header(value):
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def unique_issue_keys(values):
    keys = []
    seen = set()
    for value in values:
        key = str(value or "").strip()
        if not key or key.lower() == "none":
            continue
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def column_values_from_rows(rows, header_name="Issue key"):
    if not rows:
        return []

    expected = normalize_header(header_name)
    headers = [normalize_header(value) for value in rows[0]]
    if expected not in headers:
        raise RuntimeError("Could not find a column named 'Issue key'.")

    index = headers.index(expected)
    return unique_issue_keys(row[index] if index < len(row) else "" for row in rows[1:])


def parse_csv_issue_keys(data):
    text = data.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    return column_values_from_rows(rows)


def excel_column_index(cell_ref):
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + (ord(char.upper()) - ord("A") + 1)
    return max(index - 1, 0)


def parse_shared_strings(zip_file):
    try:
        xml_bytes = zip_file.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(xml_bytes)
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values = []
    for item in root.findall("x:si", namespace):
        texts = [node.text or "" for node in item.findall(".//x:t", namespace)]
        values.append("".join(texts))
    return values


def parse_xlsx_issue_keys(data):
    with zipfile.ZipFile(io.BytesIO(data)) as zip_file:
        shared_strings = parse_shared_strings(zip_file)
        workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
        namespace = {
            "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        }
        first_sheet = workbook.find("x:sheets/x:sheet", namespace)
        if first_sheet is None:
            raise RuntimeError("The Excel file does not contain any sheets.")

        relationship_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        relationships = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
        rel_namespace = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
        sheet_target = None
        for rel in relationships.findall("rel:Relationship", rel_namespace):
            if rel.attrib.get("Id") == relationship_id:
                sheet_target = rel.attrib.get("Target")
                break

        if not sheet_target:
            raise RuntimeError("Could not locate the first worksheet.")

        sheet_path = "xl/" + sheet_target.lstrip("/")
        sheet = ET.fromstring(zip_file.read(sheet_path))
        rows = []
        sheet_namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for row in sheet.findall(".//x:sheetData/x:row", sheet_namespace):
            values = []
            for cell in row.findall("x:c", sheet_namespace):
                index = excel_column_index(cell.attrib.get("r", "A1"))
                while len(values) <= index:
                    values.append("")

                cell_type = cell.attrib.get("t")
                value_node = cell.find("x:v", sheet_namespace)
                inline_node = cell.find("x:is/x:t", sheet_namespace)
                raw = value_node.text if value_node is not None else ""
                if cell_type == "s" and raw:
                    values[index] = shared_strings[int(raw)]
                elif cell_type == "inlineStr" and inline_node is not None:
                    values[index] = inline_node.text or ""
                else:
                    values[index] = raw or ""
            rows.append(values)

        return column_values_from_rows(rows)


def parse_issue_key_file(filename, content_base64):
    data = base64.b64decode(content_base64)
    lower_name = filename.lower()
    if lower_name.endswith(".xlsx"):
        return parse_xlsx_issue_keys(data)
    if lower_name.endswith(".csv"):
        return parse_csv_issue_keys(data)
    raise RuntimeError("Please upload a .xlsx or .csv file.")


def normalize_project_key(value):
    raw = str(value or "").strip()
    if not raw:
        return "GLS4"

    if "(" in raw and ")" in raw:
        inside = raw.rsplit("(", 1)[1].split(")", 1)[0].strip()
        if inside:
            return inside

    if "/browse/" in raw:
        issue_part = raw.rsplit("/browse/", 1)[1].split("?", 1)[0]
        if "-" in issue_part:
            return issue_part.split("-", 1)[0].strip()

    if "-" in raw and " " not in raw:
        return raw.split("-", 1)[0].strip()

    return raw


def get_settings():
    load_dotenv(str(ENV_PATH))
    config = load_config(str(CONFIG_PATH))
    base_url = os.environ.get("JIRA_BASE_URL")
    user = os.environ.get("JIRA_USER")
    token = os.environ.get("JIRA_TOKEN")
    auth_mode = os.environ.get("JIRA_AUTH_MODE", "auto").lower()
    return config, base_url, user, token, auth_mode


def save_env_settings(base_url, auth_mode, user, token):
    if auth_mode not in {"pat", "basic"}:
        raise RuntimeError("Invalid auth mode. Use pat or basic.")
    if not base_url:
        raise RuntimeError("Jira URL is required.")
    if not token:
        raise RuntimeError("Token is required.")

    values = {
        "JIRA_BASE_URL": base_url.rstrip("/"),
        "JIRA_AUTH_MODE": auth_mode,
        "JIRA_TOKEN": token,
        "JIRA_USER": user or "",
    }

    lines = [
        "JIRA_BASE_URL={JIRA_BASE_URL}",
        "JIRA_AUTH_MODE={JIRA_AUTH_MODE}",
        "JIRA_TOKEN={JIRA_TOKEN}",
        "JIRA_USER={JIRA_USER}",
    ]
    ENV_PATH.write_text("\n".join(line.format(**values) for line in lines) + "\n", encoding="utf-8")
    os.environ.update(values)
    return values


def clone_many(tickets, dry_run, target_project=None, overrides=None):
    config, base_url, user, token, auth_mode = get_settings()
    if overrides:
        if "clone_fields" in overrides:
            configured_fields = config.get("clone_fields", [])
            requested_fields = overrides.get("clone_fields") or []
            overrides["clone_fields"] = list(dict.fromkeys([*requested_fields, *configured_fields]))
        config.update(overrides)
    if not base_url:
        raise RuntimeError("Missing JIRA_BASE_URL in .env")
    if not token:
        raise RuntimeError("Missing JIRA_TOKEN in .env")
    if auth_mode not in {"auto", "pat", "basic"}:
        raise RuntimeError("Invalid JIRA_AUTH_MODE. Use auto, pat, or basic.")

    client = JiraClient(base_url, user=user, token=token, auth_mode=auth_mode)
    resolved_fields = resolve_clone_fields(client, config.get("clone_fields", []))
    fields_to_read = sorted(
        set(["summary", "project", "issuetype"]) | set(resolved_fields.values())
    )

    results = []
    for ticket in tickets:
        try:
            source_issue = client.get_issue(ticket, fields_to_read)
            expected_component = config.get("expected_component", "S4 HANA(GLS4)")
            source_components = get_component_names(source_issue)
            component_warning = None
            if (
                "components" in config.get("clone_fields", [])
                and expected_component
                and expected_component not in source_components
            ):
                component_text = ", ".join(source_components) if source_components else "empty"
                component_warning = {
                    "type": "origin_component_mismatch",
                    "message": (
                        f"Origin component is {component_text}. "
                        f"Click update to change the origin ticket component to {expected_component}."
                    ),
                    "source_components": source_components,
                    "expected_component": expected_component,
                }

            payload = build_payload(
                source_issue,
                config,
                target_project=target_project,
                resolved_fields=resolved_fields,
            )
            summary = payload["fields"]["summary"]

            if dry_run:
                results.append(
                    {
                        "source": ticket,
                        "summary": summary,
                        "status": "preview",
                        "payload": payload,
                        "warning": component_warning,
                    }
                )
                continue

            created = client.create_issue(payload)
            cloned_key = created["key"]
            linked = False
            link_error = None

            if config.get("link_to_original", True):
                try:
                    client.link_issues(ticket, cloned_key, config.get("link_type", "Cloners"))
                    linked = True
                except RuntimeError as error:
                    link_error = str(error)

            results.append(
                {
                    "source": ticket,
                    "summary": summary,
                    "clone": cloned_key,
                    "status": "created",
                    "linked": linked,
                    "link_error": link_error,
                    "warning": component_warning,
                }
            )
        except RuntimeError as error:
            results.append(
                {
                    "source": ticket,
                    "status": "error",
                    "error": str(error),
                }
            )

    return results


def update_origin_component(issue_key):
    config, base_url, user, token, auth_mode = get_settings()
    if not base_url:
        raise RuntimeError("Missing JIRA_BASE_URL in .env")
    if not token:
        raise RuntimeError("Missing JIRA_TOKEN in .env")

    expected_component = config.get("expected_component", "S4 HANA(GLS4)")
    client = JiraClient(base_url, user=user, token=token, auth_mode=auth_mode)
    client.update_issue(issue_key, {"fields": {"components": [{"name": expected_component}]}})
    return expected_component


def create_bug_issue(body):
    config, base_url, user, token, auth_mode = get_settings()
    if not base_url:
        raise RuntimeError("Missing JIRA_BASE_URL in .env")
    if not token:
        raise RuntimeError("Missing JIRA_TOKEN in .env")

    summary = body.get("summary", "").strip()
    description = body.get("description", "").strip()
    if not summary:
        raise RuntimeError("Bug summary is required.")

    project_key = normalize_project_key(body.get("project_key", "GLS4"))
    issue_type = body.get("issue_type", "Bug").strip() or "Bug"

    fields = {
        "project": {"key": project_key},
        "issuetype": {"name": issue_type},
        "summary": summary,
        "description": description,
    }

    priority_id = body.get("priority_id", "").strip()
    if priority_id:
        fields["priority"] = {"id": priority_id}

    labels = body.get("labels", [])
    if isinstance(labels, str):
        labels = [label.strip() for label in labels.replace(",", "\n").splitlines()]
    fields["labels"] = [label for label in labels if label]

    components = body.get("components", "S4 HANA(GLS4)")
    if isinstance(components, str):
        components = [component.strip() for component in components.replace(",", "\n").splitlines()]
    clean_components = [component for component in components if component]
    if clean_components:
        fields["components"] = [{"name": component} for component in clean_components]

    client = JiraClient(base_url, user=user, token=token, auth_mode=auth_mode)
    current_user = client.get_myself()
    reporter_name = current_user.get("name")
    if reporter_name:
        fields["assignee"] = {"name": reporter_name}

    test_phase = body.get("test_phase", "").strip()
    if issue_type == "Bug" and test_phase and test_phase.lower() != "none":
        test_phase_field = resolve_clone_fields(client, ["Test Phase"])["Test Phase"]
        fields[test_phase_field] = {"value": test_phase}

    created = client.create_issue({"fields": fields})
    return {"key": created["key"], "payload": {"fields": fields}, "base_url": base_url}


def get_issue_transitions(issue_key):
    config, base_url, user, token, auth_mode = get_settings()
    if not base_url:
        raise RuntimeError("Missing JIRA_BASE_URL in .env")
    if not token:
        raise RuntimeError("Missing JIRA_TOKEN in .env")

    client = JiraClient(base_url, user=user, token=token, auth_mode=auth_mode)
    issue = client.get_issue(issue_key, ["status"])
    current_status = issue.get("fields", {}).get("status", {}).get("name")
    data = client.get_transitions(issue_key)
    transitions = []
    for transition in data.get("transitions", []):
        target = transition.get("to", {})
        transitions.append(
            {
                "id": transition.get("id"),
                "name": transition.get("name"),
                "to_status": target.get("name"),
            }
        )
    return {"current_status": current_status, "transitions": transitions}


def update_issue_transition(issue_key, transition_id, bug_category=None):
    config, base_url, user, token, auth_mode = get_settings()
    if not base_url:
        raise RuntimeError("Missing JIRA_BASE_URL in .env")
    if not token:
        raise RuntimeError("Missing JIRA_TOKEN in .env")
    if not issue_key:
        raise RuntimeError("Missing issue key.")
    if not transition_id:
        raise RuntimeError("Missing transition.")

    client = JiraClient(base_url, user=user, token=token, auth_mode=auth_mode)
    fields = {}
    if bug_category and bug_category.lower() != "none":
        fields["customfield_11850"] = {"value": bug_category}
    client.transition_issue(issue_key, transition_id, fields=fields)
    return get_issue_transitions(issue_key)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            path = "/index.html"

        target = (WEB_ROOT / path.lstrip("/")).resolve()
        if not str(target).startswith(str(WEB_ROOT.resolve())) or not target.exists():
            self.send_error(404)
            return

        content_type = "text/plain; charset=utf-8"
        if target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"

        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def do_GET(self):
        if self.path == "/api/config":
            config, base_url, user, token, auth_mode = get_settings()
            self.send_json(
                200,
                {
                    "base_url": base_url,
                    "user": user,
                    "token_set": bool(token),
                    "auth_mode": auth_mode,
                    "config": config,
                },
            )
            return
        self.serve_static()

    def do_POST(self):
        if self.path == "/api/config":
            try:
                body = self.read_body()
                saved = save_env_settings(
                    base_url=body.get("base_url", "").strip(),
                    auth_mode=body.get("auth_mode", "pat").strip().lower(),
                    user=body.get("user", "").strip(),
                    token=body.get("token", "").strip(),
                )
                self.send_json(
                    200,
                    {
                        "base_url": saved["JIRA_BASE_URL"],
                        "user": saved["JIRA_USER"],
                        "token_set": True,
                        "auth_mode": saved["JIRA_AUTH_MODE"],
                    },
                )
            except RuntimeError as error:
                self.send_json(400, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": f"Unexpected error: {error}"})
            return

        if self.path == "/api/component":
            try:
                body = self.read_body()
                issue_key = body.get("issue_key", "").strip()
                if not issue_key:
                    self.send_json(400, {"error": "Missing issue key."})
                    return
                component = update_origin_component(issue_key)
                self.send_json(200, {"issue_key": issue_key, "component": component})
            except RuntimeError as error:
                self.send_json(502, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": f"Unexpected error: {error}"})
            return

        if self.path == "/api/issue-keys":
            try:
                body = self.read_body()
                filename = body.get("filename", "")
                content_base64 = body.get("content_base64", "")
                if not filename or not content_base64:
                    self.send_json(400, {"error": "Missing uploaded file."})
                    return
                issue_keys = parse_issue_key_file(filename, content_base64)
                self.send_json(200, {"issue_keys": issue_keys, "count": len(issue_keys)})
            except RuntimeError as error:
                self.send_json(400, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": f"Unexpected error: {error}"})
            return

        if self.path == "/api/bug":
            try:
                body = self.read_body()
                result = create_bug_issue(body)
                self.send_json(200, result)
            except RuntimeError as error:
                self.send_json(502, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": f"Unexpected error: {error}"})
            return

        if self.path == "/api/transitions":
            try:
                body = self.read_body()
                issue_key = body.get("issue_key", "").strip()
                if not issue_key:
                    self.send_json(400, {"error": "Missing issue key."})
                    return

                if body.get("transition_id"):
                    workflow = update_issue_transition(
                        issue_key,
                        body.get("transition_id"),
                        bug_category=body.get("bug_category", ""),
                    )
                    self.send_json(
                        200,
                        {
                            "issue_key": issue_key,
                            "updated": True,
                            "current_status": workflow["current_status"],
                            "transitions": workflow["transitions"],
                        },
                    )
                else:
                    workflow = get_issue_transitions(issue_key)
                    self.send_json(
                        200,
                        {
                            "issue_key": issue_key,
                            "updated": False,
                            "current_status": workflow["current_status"],
                            "transitions": workflow["transitions"],
                        },
                    )
            except RuntimeError as error:
                self.send_json(502, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": f"Unexpected error: {error}"})
            return

        if self.path != "/api/clone":
            self.send_error(404)
            return

        try:
            body = self.read_body()
            tickets = parse_tickets(body.get("tickets", ""))
            if not tickets:
                self.send_json(400, {"error": "Please enter at least one Jira ticket."})
                return

            results = clone_many(
                tickets=tickets,
                dry_run=bool(body.get("dry_run", True)),
                target_project=body.get("target_project") or None,
                overrides={
                    "summary_prefix": body.get("summary_prefix", "CLONE - "),
                    "clone_fields": body.get("clone_fields", []),
                    "link_to_original": bool(body.get("link_to_original", True)),
                    "link_type": body.get("link_type", "Cloners"),
                },
            )
            self.send_json(200, {"results": results})
        except RuntimeError as error:
            self.send_json(502, {"error": str(error)})
        except Exception as error:
            self.send_json(500, {"error": f"Unexpected error: {error}"})


def main():
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Jira clone web app running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
