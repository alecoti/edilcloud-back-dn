from pathlib import Path
import re
import shutil
import subprocess
import sys
import pytest


@pytest.mark.parametrize("failure", ["none", "build", "start", "health", "switch", "workers"])
def test_live_slot_is_not_stopped_until_candidate_is_ready(failure):
    bash = "C:/Program Files/Git/bin/bash.exe" if sys.platform == "win32" else shutil.which("bash")
    if not bash or not Path(bash).exists():
        pytest.skip("Bash is required for the actual deploy function")
    workflow = (Path(__file__).parents[1] / ".github/workflows/deploy-production.yml").read_text()
    function = re.search(
        r"          deploy_blue_green\(\) \{.*?\n          \}", workflow, re.S
    ).group()
    script = (
        """ACTIVE_SLOT=blue
NEXT_SLOT=green
KEEP_PREVIOUS_SLOT_HOT=false
step() { echo "$1"; test "$1" != "$FAILURE"; }
build_slot() { step build; }
start_slot_web() { step start; }
slot_port() { echo 18002; }
healthcheck() { step health; }
switch_live_backend() { step switch; }
start_slot_worker() { step workers; }
slot_worker_service() { echo assistant-worker-blue; }
slot_push_worker_service() { echo notification-worker-blue; }
slot_document_worker_service() { echo elaborati-worker-blue; }
slot_web_service() { echo web-blue; }
compose_cmd() { if [ "$1" = config ]; then echo elaborati-worker-blue; else echo stop-old; fi; }
write_active_slot() { echo active-green; }
"""
        + function
        + f"\nFAILURE={failure}\nif deploy_blue_green; then echo success; else echo rejected; fi\n"
    )
    result = subprocess.run([bash, "-c", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    if failure == "none":
        assert (
            lines.index("health")
            < lines.index("switch")
            < lines.index("workers")
            < lines.index("stop-old")
            < lines.index("active-green")
        )
        assert lines[-1] == "success"
    else:
        assert lines[-1] == "rejected"
        assert "stop-old" not in lines and "active-green" not in lines
