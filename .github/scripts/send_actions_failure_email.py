#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_BASE = "https://api.github.com"
FAILED_CONCLUSIONS = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}
BODY_LOG_LINE_LIMIT = 120
BODY_LOG_CHAR_LIMIT = 12000


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def required_env(name: str) -> str:
    value = env(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def github_request(url: str, *, token: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "edilcloud-ci-failure-mailer",
        },
    )
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def github_log_request(url: str, *, token: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "edilcloud-ci-failure-mailer",
        },
    )
    with urlopen(request, timeout=60) as response:
        payload = response.read()
    return payload.decode("utf-8", errors="replace")


def iter_run_jobs(*, repository: str, run_id: str, token: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    next_url = f"{API_BASE}/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100"
    while next_url:
        data = github_request(next_url, token=token)
        jobs.extend(data.get("jobs", []))
        next_url = ""
        # GitHub pagination can be ignored here in most cases; keeping explicit fallback.
        if len(data.get("jobs", [])) == 100:
            page = 2 + (len(jobs) // 100) - 1
            next_url = f"{API_BASE}/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100&page={page}"
    return jobs


def summarize_steps(job: dict[str, Any]) -> str:
    failed_steps = [
        step.get("name", "Unnamed step")
        for step in job.get("steps", [])
        if step.get("conclusion") in FAILED_CONCLUSIONS
    ]
    if failed_steps:
        return ", ".join(failed_steps)
    return "N/A"


def excerpt_log(text: str) -> str:
    lines = text.splitlines()
    excerpt = "\n".join(lines[-BODY_LOG_LINE_LIMIT:])
    if len(excerpt) > BODY_LOG_CHAR_LIMIT:
        excerpt = excerpt[-BODY_LOG_CHAR_LIMIT:]
    return excerpt.strip() or "(log vuoto)"


def build_email_body(*, failed_jobs: list[dict[str, Any]], run_url: str) -> str:
    repository = env("GITHUB_REPOSITORY")
    workflow = env("GITHUB_WORKFLOW")
    ref_name = env("GITHUB_REF_NAME")
    sha = env("GITHUB_SHA")
    actor = env("GITHUB_ACTOR")
    event_name = env("GITHUB_EVENT_NAME")
    lines = [
        "GitHub Actions failure alert",
        "",
        f"Repository: {repository}",
        f"Workflow: {workflow}",
        f"Branch: {ref_name}",
        f"Commit: {sha}",
        f"Actor: {actor}",
        f"Event: {event_name}",
        f"Run URL: {run_url}",
        "",
        "Failed jobs:",
    ]
    for job in failed_jobs:
        lines.extend(
            [
                "",
                f"- Job: {job.get('name', 'Unnamed job')}",
                f"  Conclusion: {job.get('conclusion', 'unknown')}",
                f"  Failed steps: {summarize_steps(job)}",
                "  Log excerpt:",
                excerpt_log(job.get("log_text", "")),
            ]
        )
    lines.extend(
        [
            "",
            "Full logs are attached as failed-jobs.log.txt",
        ]
    )
    return "\n".join(lines)


def build_log_attachment(*, failed_jobs: list[dict[str, Any]], run_url: str) -> str:
    chunks = [
        f"Workflow failure log bundle\nRun URL: {run_url}\nRepository: {env('GITHUB_REPOSITORY')}\nWorkflow: {env('GITHUB_WORKFLOW')}\nBranch: {env('GITHUB_REF_NAME')}\nCommit: {env('GITHUB_SHA')}\n"
    ]
    for job in failed_jobs:
        chunks.append(
            "\n".join(
                [
                    "",
                    "=" * 96,
                    f"JOB: {job.get('name', 'Unnamed job')}",
                    f"CONCLUSION: {job.get('conclusion', 'unknown')}",
                    f"FAILED STEPS: {summarize_steps(job)}",
                    "=" * 96,
                    job.get("log_text", "") or "(log vuoto)",
                ]
            )
        )
    return "\n".join(chunks)


def send_email(*, body: str, attachment_text: str) -> None:
    smtp_host = env("CI_FAILURE_SMTP_HOST")
    smtp_port = int(env("CI_FAILURE_SMTP_PORT", "465") or "465")
    smtp_username = env("CI_FAILURE_SMTP_USERNAME")
    smtp_password = env("CI_FAILURE_SMTP_PASSWORD")
    email_to = env("CI_FAILURE_EMAIL_TO")
    email_from = env("CI_FAILURE_EMAIL_FROM", smtp_username)

    missing = [
        name
        for name, value in [
            ("CI_FAILURE_SMTP_HOST", smtp_host),
            ("CI_FAILURE_SMTP_PORT", str(smtp_port)),
            ("CI_FAILURE_SMTP_USERNAME", smtp_username),
            ("CI_FAILURE_SMTP_PASSWORD", smtp_password),
            ("CI_FAILURE_EMAIL_TO", email_to),
            ("CI_FAILURE_EMAIL_FROM", email_from),
        ]
        if not value
    ]
    if missing:
        print(
            "Failure email skipped because SMTP configuration is incomplete: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        return

    subject = (
        f"[EdilCloud CI] FAIL {env('GITHUB_WORKFLOW')} "
        f"{env('GITHUB_REF_NAME')} {env('GITHUB_SHA')[:7]}"
    )
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = email_from
    message["To"] = email_to
    message.set_content(body)
    message.add_attachment(
        attachment_text.encode("utf-8"),
        maintype="text",
        subtype="plain",
        filename="failed-jobs.log.txt",
    )

    context = ssl.create_default_context()
    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=60) as server:
            server.login(smtp_username, smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=60) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(smtp_username, smtp_password)
            server.send_message(message)


def main() -> int:
    try:
        github_token = required_env("GITHUB_TOKEN")
        repository = required_env("GITHUB_REPOSITORY")
        run_id = required_env("GITHUB_RUN_ID")
        run_url = f"{env('GITHUB_SERVER_URL', 'https://github.com')}/{repository}/actions/runs/{run_id}"

        jobs = iter_run_jobs(repository=repository, run_id=run_id, token=github_token)
        failed_jobs = [job for job in jobs if job.get("conclusion") in FAILED_CONCLUSIONS]
        if not failed_jobs:
            print("No failed jobs found for this workflow run.")
            return 0

        for job in failed_jobs:
            log_url = f"{API_BASE}/repos/{repository}/actions/jobs/{job['id']}/logs"
            try:
                job["log_text"] = github_log_request(log_url, token=github_token)
            except HTTPError as exc:
                job["log_text"] = f"Unable to download log for job #{job.get('id')}: HTTP {exc.code}"
            except URLError as exc:
                job["log_text"] = f"Unable to download log for job #{job.get('id')}: {exc.reason}"

        body = build_email_body(failed_jobs=failed_jobs, run_url=run_url)
        attachment_text = build_log_attachment(failed_jobs=failed_jobs, run_url=run_url)

        output_dir = Path(env("RUNNER_TEMP", ".")) / "ci-failure-mail"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "failed-jobs.log.txt").write_text(attachment_text, encoding="utf-8")
        (output_dir / "email-preview.txt").write_text(body, encoding="utf-8")

        send_email(body=body, attachment_text=attachment_text)
        print("Failure email processing completed.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Failure email job crashed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
