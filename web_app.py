#!/usr/bin/env python3
import json
import os
import urllib.parse
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
