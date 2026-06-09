# Jira Batch Clone Tool

Small CLI for cloning multiple Jira stories from a text file.

This tool does not use a special Jira "clone" REST endpoint. It reads each source issue, builds a new issue payload from configured fields, creates the new issue, and can optionally link the new issue back to the source.

## Files

- `clone_jira.py`: CLI tool.
- `web_app.py`: local web server.
- `web/`: browser UI.
- `tickets.txt`: one Jira issue key per line.
- `tickets.example.txt`: safe example ticket list for GitHub.
- `clone-config.example.json`: fields and clone behavior.
- `.env.example`: environment variables.

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in your Jira URL and token.
3. Copy `clone-config.example.json` to `clone-config.json`.
4. Copy `tickets.example.txt` to `tickets.txt`.
5. Adjust the `clone_fields` list if your Jira project requires custom fields.

For Jira Data Center personal access tokens, use:

```powershell
$env:JIRA_AUTH_MODE="pat"
$env:JIRA_TOKEN="your-token"
```

For username/password or username/API token auth:

```powershell
$env:JIRA_AUTH_MODE="basic"
$env:JIRA_USER="your-user"
$env:JIRA_TOKEN="your-token-or-password"
```

## Usage

Preview without creating issues:

```powershell
python .\clone_jira.py --tickets .\tickets.txt --config .\clone-config.json --dry-run
```

Create cloned issues:

```powershell
python .\clone_jira.py --tickets .\tickets.txt --config .\clone-config.json
```

Clone into another project:

```powershell
python .\clone_jira.py --tickets .\tickets.txt --target-project GLS4
```

## Web UI

Start the local website:

```powershell
python .\web_app.py
```

Open:

```text
http://127.0.0.1:8765
```

The website reads Jira credentials from `.env` and clone behavior from `clone-config.json`. Keep `Preview` enabled for the first run. Turn it off only when the generated payload looks right.

Different users can update the Jira credential in the `Connection` section. Paste the current user's token, choose `Personal Access Token` or `Basic Auth`, then click `Save`.

The Batch page also supports uploading `.xlsx` or `.csv` files. The file must contain a column named `Issue key`; those values are loaded into the ticket list for Preview or Create.

## Create

The web UI also includes a `Create` page. The default project is:

- Global Logistics S4 (`GLS4`)

Open:

```text
http://127.0.0.1:8765/bug.html
```

Users can change the project key and select one of these issue types:

- Bug
- Epic
- Story
- Technical Story
- PPS Bug
- Test

For `Bug`, the page includes a `Test Phase` field with `None`, `Standalone SIT`, and `DEV Test`.

The Create page also includes a `Component` selector. It defaults to `S4 HANA(GLS4)`, with `LLGW`, `S4 HANA(GLS4)`, and `global Logisite` as options.

After an issue is created, the page loads its available Jira workflow transitions and shows an `Update Status` control.

Some workflow transitions require `Bug Category`. The Bug Category selector is shown only when the selected transition is `Ready for Testing`.

For newly created issues, assignee is automatically set to the current Jira user, matching the default reporter.

## Publishing to GitHub

This repository can be public as source code only. Do not publish live credentials or internal ticket lists.

Safe to commit:

- `clone_jira.py`
- `web_app.py`
- `web/`
- `.env.example`
- `clone-config.example.json`
- `tickets.example.txt`
- `README.md`
- `SECURITY.md`

Do not commit:

- `.env`
- `clone-config.json`
- `tickets.txt`
- Jira tokens, passwords, cookies, or real internal ticket lists

This is not a normal static webpage. It needs the Python backend because browser-only JavaScript should not hold Jira tokens and may be blocked by Jira CORS rules.

## Notes

- Required create fields vary by Jira project. If Jira returns a validation error, add the missing field to `clone-config.json` or set a default value there.
- Reporter and assignee are copied when Jira allows the current user to set those fields. If Jira rejects `reporter`, your account may need the Modify Reporter permission.
- Custom fields can be listed by their Jira display name, such as `Background`, `Work Stream`, `Sub-workstream`, `Requirement Type`, or `IT Owner`. The tool resolves them to `customfield_xxxxx` automatically.
- If the source component is not `S4 HANA(GLS4)`, the website shows a reminder and provides an `Update origin` button to update the original Jira ticket's component.
- In the web UI, each ticket is processed independently. If one ticket fails, the result keeps that source ticket ID and the remaining tickets continue.
- Attachments, comments, sub-tasks, sprint, status, created date, and history are not copied by this first version.
- Keep `.env` private. Do not commit tokens.
