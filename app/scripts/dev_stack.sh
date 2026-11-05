#!/usr/bin/env bash
# Development stack for RPG NeuralMesh: stand-in model, registered nodes, API, MCP gateway and the Vite UI.
# Logs go to app/.neuralmesh/logs. Run from anywhere.
#
#   scripts/dev_stack.sh start            start everything (API uses NEURALMESH_MODEL_POLICY, default the stand-in policy)
#   scripts/dev_stack.sh stop             stop everything
#   scripts/dev_stack.sh status           listeners per port and the API health
#   scripts/dev_stack.sh restart-node ID  restart one node after its pack changed
#   scripts/dev_stack.sh restart-api      restart the API and the gateway (they cache the node registry at start)
set -u
cd "$(dirname "$0")/.."
PY=${PYTHON:-../.venv/bin/python}
LOGS=.neuralmesh/logs
mkdir -p "$LOGS"
export NEURALMESH_MODEL_POLICY=${NEURALMESH_MODEL_POLICY:-config/model_policy.dev-standin.json}

nodes() { "$PY" -c "from shared.registry import node_ids; print(' '.join(node_ids()))"; }
port_of() { "$PY" -c "from shared.registry import node; print(node('$1').port)"; }
listeners() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null; }
kill_port() { local pids; pids=$(listeners "$1"); [ -n "$pids" ] && kill $pids 2>/dev/null; return 0; }
start_node() { nohup "$PY" -m mcp_nodes "$1" > "$LOGS/$1.log" 2>&1 < /dev/null & }
start_api() {
  nohup "$PY" -m uvicorn api.main:app --host 127.0.0.1 --port 8000 > "$LOGS/api.log" 2>&1 < /dev/null &
  nohup "$PY" -m mcp_gateway.server > "$LOGS/gateway.log" 2>&1 < /dev/null &
}
all_ports() { echo 11435 8000 8100 5173; for n in $(nodes); do port_of "$n"; done; }

case "${1:-status}" in
  start)
    nohup "$PY" -m evaluations.standin_model_server > "$LOGS/standin.log" 2>&1 < /dev/null &
    for n in $(nodes); do start_node "$n"; done
    sleep 5
    start_api
    (cd ui && nohup npm run dev -- --host 127.0.0.1 --port 5173 > "../$LOGS/ui.log" 2>&1 < /dev/null &)
    sleep 10
    "$0" status
    ;;
  stop)
    for p in $(all_ports); do kill_port "$p"; done
    sleep 1
    echo "stopped"
    ;;
  restart-node)
    kill_port "$(port_of "$2")"
    sleep 1
    start_node "$2"
    sleep 5
    echo "$2 listeners: $(listeners "$(port_of "$2")" | wc -l | tr -d ' ')"
    ;;
  restart-api)
    kill_port 8000; kill_port 8100
    sleep 1
    start_api
    sleep 10
    curl -s http://127.0.0.1:8000/health; echo
    ;;
  status)
    for p in $(all_ports); do echo "port $p listeners: $(listeners "$p" | wc -l | tr -d ' ')"; done
    echo "API health: $(curl -s --max-time 5 http://127.0.0.1:8000/health)"
    echo "stand-in model: $(curl -s --max-time 5 http://127.0.0.1:11435/control)"
    ;;
  *)
    echo "usage: $0 start|stop|status|restart-node <id>|restart-api"; exit 2 ;;
esac
