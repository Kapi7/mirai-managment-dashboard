"""Run the existing dashboard and isolated reports processes on one Render service.

Report jobs are opt-in. A verified state snapshot is required before enabling them.
Reports failures restart only the affected reports process. A dashboard exit
stops all children so Render can restart the service cleanly.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STATE_NAMES = ('.monitor_seen_orders.json', '.orders_state.json',
               '.telegram_seen_orders.json', '.telegram_summary_state.json')


def reports_environment(parent):
    config = Path(parent['REPORTS_ENV_FILE'])
    values = json.loads(config.read_text())
    if not isinstance(values, dict) or any(not isinstance(v, str) for v in values.values()):
        raise ValueError('Reports environment must be a JSON object of strings')
    # Keep runtime plumbing, but never inherit dashboard integration credentials.
    env = {k: parent[k] for k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'SSL_CERT_FILE') if k in parent}
    env.update(values)
    data = Path(parent['REPORTS_DATA_DIR']).resolve()
    if not data.is_dir():
        raise ValueError('Reports data directory must already exist')
    env.update(OUTPUT_DIR=str(data), OUTPUTS_DIR=str(data), SEEN_FILE=str(data / STATE_NAMES[0]),
               SHOP_BILLS_STATE_FILE=str(data / '.shop_bills_state.json'),
               STATE_FILE=str(data / STATE_NAMES[1]),
               TELEGRAM_SEEN_ORDERS_FILE=str(data / STATE_NAMES[2]),
               TELEGRAM_SEEN_FILE=str(data / STATE_NAMES[2]),
               SUMMARY_STATE_FILE=str(data / STATE_NAMES[3]),
               REPORTS_JOBS_ENABLED=parent.get('REPORTS_JOBS_ENABLED', '0'),
               PORT='8081', PYTHONUNBUFFERED='1')
    if env.get('ALERT_FORCE_ON_START', '0') != '0':
        raise ValueError('ALERT_FORCE_ON_START must be disabled during consolidation')
    if env['REPORTS_JOBS_ENABLED'] == '1':
        manifest = json.loads((data / 'cutover-manifest.json').read_text())
        if manifest.get('source_suspended') is not True:
            raise ValueError('Source reports service must be suspended before enabling jobs')
        accepted = data / '.cutover-accepted'
        manifest_hash = hashlib.sha256((data / 'cutover-manifest.json').read_bytes()).hexdigest()
        previously_accepted = accepted.is_file() and accepted.read_text() == manifest_hash
        for name in STATE_NAMES:
            file = data / name
            if not file.is_file():
                raise ValueError('Missing reports state: ' + name)
            json.loads(file.read_text())
            if not previously_accepted and hashlib.sha256(file.read_bytes()).hexdigest() != manifest.get('sha256', {}).get(name):
                raise ValueError('State snapshot hash mismatch: ' + name)
        accepted.write_text(manifest_hash)
        accepted.chmod(0o600)
    return env


def stop_all(children):
    for child in children:
        # A dead gateway can still have a live Python descendant in its group.
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline and any(p.poll() is None for p in children):
        time.sleep(.1)
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()


def main():
    parent = dict(os.environ)
    commands = [('dashboard', ['bash', 'start.sh'], ROOT, parent)]
    if parent.get('REPORTS_ENABLED', '0') == '1':
        env = reports_environment(parent)
        python = str(ROOT / '.reports-venv/bin/python')
        commands.append(('reports-api', [python, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', '8081'], ROOT / 'automation_reports', env))
        if env['REPORTS_JOBS_ENABLED'] == '1':
            commands.append(('reports-loop', [python, '-u', 'master_report_mirai.py', '--every', '1800'], ROOT / 'automation_reports', env))
    children = []
    def terminate(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        for name, command, cwd, env in commands:
            children.append(subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True))
            print('[consolidation] Started ' + name, flush=True)
        restart_at = {}
        while True:
            for i, child in enumerate(children):
                if child.poll() is None:
                    continue
                if i == 0:
                    raise RuntimeError('Dashboard process exited')
                # Match the old report loop's ten-second restart delay, without
                # restarting the dashboard or unrelated report processes.
                now = time.monotonic()
                if i not in restart_at:
                    restart_at[i] = now + 10
                    print('[consolidation] Reports process exited; restart in 10s', flush=True)
                if now >= restart_at[i]:
                    name, command, cwd, env = commands[i]
                    children[i] = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
                    del restart_at[i]
                    print('[consolidation] Restarted ' + name, flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        stop_all(children)


if __name__ == '__main__':
    sys.exit(main())
