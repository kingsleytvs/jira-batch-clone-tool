#!/usr/bin/env python3
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_CONFIG = {
    "summary_prefix": "CLONE - ",
    "target_project": None,
    "expected_component": "S4 HANA(GLS4)",
    "clone_fields": [
        "description",
        "priority",
        "labels",
        "components",
        "versions",
        "fixVersions",
    ],
    "defaults": {},
    "link_to_original": True,
    "link_type": "Cloners",
}


SYSTEM_FIELDS = {
    "assignee",
    "components",
    "description",
    "fixVersions",
    "labels",
    "priority",
    "reporter",
    "versions",
}


def load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path):
    config = dict(DEFAULT_CONFIG)
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as file:
            config.update(json.load(file))
    return config


def read_tickets(path):
    with open(path, "r", encoding="utf-8") as file:
        tickets = []
        for raw_line in file:
            line = raw_line.strip()
            if line and not line.startswith("#"):
                tickets.append(line)
        return tickets


class JiraClient:
    def __init__(self, base_url, user=None, token=None, auth_mode="auto"):
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.token = token
        self.auth_mode = auth_mode

    def request(self, method, path, body=None):
        url = self.base_url + path
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        if self.auth_mode == "basic" and self.user and self.token:
            raw = f"{self.user}:{self.token}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        elif self.auth_mode == "pat" and self.token:
            headers["Authorization"] = "Bearer " + self.token
        elif self.user and self.token:
            raw = f"{self.user}:{self.token}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        elif self.token:
            headers["Authorization"] = "Bearer " + self.token

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read().decode("utf-8")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {url} failed: HTTP {error.code} {detail}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"{method} {url} failed: {error.reason}") from error

    def get_issue(self, issue_key, fields):
        encoded_fields = urllib.parse.quote(",".join(fields))
        return self.request("GET", f"/rest/api/2/issue/{issue_key}?fields={encoded_fields}")

    def create_issue(self, payload):
        return self.request("POST", "/rest/api/2/issue", payload)

    def update_issue(self, issue_key, payload):
        return self.request("PUT", f"/rest/api/2/issue/{issue_key}", payload)

    def link_issues(self, source_key, cloned_key, link_type):
        payload = {
            "type": {"name": link_type},
            "inwardIssue": {"key": cloned_key},
            "outwardIssue": {"key": source_key},
        }
        return self.request("POST", "/rest/api/2/issueLink", payload)

    def get_fields(self):
        return self.request("GET", "/rest/api/2/field")


def normalize_field_name(value):
    return " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())


def resolve_clone_fields(client, clone_fields):
    resolved = {}
    custom_fields = None

    for field_name in clone_fields:
        if field_name in SYSTEM_FIELDS or field_name.startswith("customfield_"):
            resolved[field_name] = field_name
            continue

        if custom_fields is None:
            custom_fields = {}
            for field in client.get_fields():
                name = field.get("name")
                field_id = field.get("id")
                if name and field_id:
                    custom_fields[normalize_field_name(name)] = field_id

        field_id = custom_fields.get(normalize_field_name(field_name))
        if not field_id:
            raise RuntimeError(f"Could not find Jira field named '{field_name}'. Check the field label in Jira.")
        resolved[field_name] = field_id

    return resolved


def copy_field(value, field_name=None):
    if isinstance(value, dict):
        if field_name in {"reporter", "assignee"} and "name" in value:
            return {"name": value["name"]}
        if field_name == "components" and "name" in value:
            return {"name": value["name"]}
        if "displayName" in value and "name" in value:
            return {"name": value["name"]}
        if "id" in value:
            return {"id": value["id"]}
        if "key" in value:
            return {"key": value["key"]}
        if "name" in value:
            return {"name": value["name"]}
    if isinstance(value, list):
        return [copy_field(item, field_name=field_name) for item in value]
    return value


def get_component_names(source_issue):
    components = source_issue.get("fields", {}).get("components") or []
    return [component.get("name") for component in components if component.get("name")]


def build_payload(source_issue, config, target_project=None, resolved_fields=None):
    resolved_fields = resolved_fields or {field: field for field in config.get("clone_fields", [])}
    fields = source_issue["fields"]
    project_key = target_project or config.get("target_project")
    if not project_key:
        project_key = fields["project"]["key"]

    payload_fields = {
        "project": {"key": project_key},
        "issuetype": {"id": fields["issuetype"]["id"]},
        "summary": f"{config.get('summary_prefix', '')}{fields['summary']}",
    }

    for field_name in config.get("clone_fields", []):
        source_field = resolved_fields.get(field_name, field_name)
        value = fields.get(source_field)
        if value is not None:
            payload_fields[source_field] = copy_field(value, field_name=field_name)

    for field_name, value in config.get("defaults", {}).items():
        payload_fields[field_name] = value

    return {"fields": payload_fields}


def print_json(label, value):
    print(label)
    print(json.dumps(value, indent=2, ensure_ascii=True))


def main():
    parser = argparse.ArgumentParser(description="Clone multiple Jira issues.")
    parser.add_argument("--tickets", default="tickets.txt", help="Text file containing issue keys.")
    parser.add_argument("--config", default="clone-config.json", help="JSON config file.")
    parser.add_argument("--env", default=".env", help="Dotenv file.")
    parser.add_argument("--base-url", default=None, help="Jira base URL.")
    parser.add_argument("--target-project", default=None, help="Target Jira project key.")
    parser.add_argument("--dry-run", action="store_true", help="Show payloads without creating issues.")
    args = parser.parse_args()

    load_dotenv(args.env)
    config = load_config(args.config)

    base_url = args.base_url or os.environ.get("JIRA_BASE_URL")
    user = os.environ.get("JIRA_USER")
    token = os.environ.get("JIRA_TOKEN")
    auth_mode = os.environ.get("JIRA_AUTH_MODE", "auto").lower()

    if not base_url:
        print("Missing JIRA_BASE_URL. Set it in .env or pass --base-url.", file=sys.stderr)
        return 2
    if not token:
        print("Missing JIRA_TOKEN. Set it in .env before reading or creating issues.", file=sys.stderr)
        return 2
    if auth_mode not in {"auto", "pat", "basic"}:
        print("Invalid JIRA_AUTH_MODE. Use auto, pat, or basic.", file=sys.stderr)
        return 2

    tickets = read_tickets(args.tickets)
    if not tickets:
        print(f"No tickets found in {args.tickets}.", file=sys.stderr)
        return 2

    client = JiraClient(base_url, user=user, token=token, auth_mode=auth_mode)
    resolved_fields = resolve_clone_fields(client, config.get("clone_fields", []))
    fields_to_read = sorted(
        set(["summary", "project", "issuetype"]) | set(resolved_fields.values())
    )

    results = []
    for ticket in tickets:
        print(f"Reading {ticket}...")
        source_issue = client.get_issue(ticket, fields_to_read)
        payload = build_payload(
            source_issue,
            config,
            target_project=args.target_project,
            resolved_fields=resolved_fields,
        )

        if args.dry_run:
            print_json(f"Payload for {ticket}:", payload)
            results.append({"source": ticket, "dry_run": True})
            continue

        created = client.create_issue(payload)
        cloned_key = created["key"]
        print(f"Created {cloned_key} from {ticket}")

        if config.get("link_to_original", True):
            try:
                client.link_issues(ticket, cloned_key, config.get("link_type", "Cloners"))
                print(f"Linked {cloned_key} to {ticket}")
            except RuntimeError as error:
                print(f"Warning: could not link {cloned_key} to {ticket}: {error}", file=sys.stderr)

        results.append({"source": ticket, "clone": cloned_key})

    print_json("Done:", results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
