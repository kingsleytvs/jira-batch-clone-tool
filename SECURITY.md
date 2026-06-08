# Security

This project is safe to publish as source code, but Jira credentials and internal ticket data must stay local.

## Do Not Commit

- `.env`
- `clone-config.json`
- `tickets.txt`
- Any Jira personal access token, password, cookie, or session value
- Internal ticket lists, screenshots, or payloads that contain confidential data

## Recommended Usage

Run the web UI locally or on an internal company server:

```powershell
python .\web_app.py
```

Then open:

```text
http://127.0.0.1:8765
```

Each user should enter their own Jira token in the website's `Connection` section. Tokens are saved only to the local `.env` file.

## Public Hosting Warning

Do not host this as a public static website. Jira cloning requires backend API calls, and Jira tokens must not be exposed in browser-side code.

If a shared deployment is needed, deploy it inside the company network with authentication and HTTPS.
