# Account AI exemption and deployment continuity

Administrative exemptions live in the billing owner's metadata as the boolean `ai_quota_unlimited`. They apply to every workspace billed to that owner, including Elaborati job reservations and provider input-budget checks. Actual usage remains recorded; purchased token credits are not deducted while the exemption is enabled. Other owners retain the existing limits. The billing API exposes an additive `ai_tokens.unlimited` field; numeric usage fields retain their existing contract.

Use `python manage.py set_account_ai_quota --owner-user-id ID --unlimited --reason "Explicit owner request"` to grant the exemption; use `--limited` to revoke it and `--dry-run` to inspect. Changes retain an audit in account metadata. Customer API payloads cannot set this flag. No phone number or individual account is hardcoded in application code.

Production uses the existing blue/green workflow. Nginx must reference `edilcloud_backend_upstream`, defined by `/etc/nginx/conf.d/edilcloud-back-upstream.conf`. Set the production deployment config and its GitHub `PROD_DEPLOY_CONFIG` secret to `DEPLOY_STRATEGY=blue_green` and `PROXY_SWITCH_STRATEGY=nginx_upstream_file`. The candidate is built and passes health checks before Nginx is reloaded; workers are started before the previous workers stop. `KEEP_PREVIOUS_SLOT_HOT=true` preserves the previous web container for established connections and a warm rollback. Builds, startup, proxy switching and worker failures explicitly propagate instead of continuing under a conditional Bash invocation. Missing proxy switching is an error rather than a silent downgrade to rolling deployment.

System dependencies in Docker are cached before source files, so ordinary Python edits no longer reinstall Chromium and the font packages.

Validation includes isolated-owner quota and usage tests, reversible administrative changes, and execution of the actual Bash blue/green function with injected failures at build, startup, health, proxy and worker stages.
