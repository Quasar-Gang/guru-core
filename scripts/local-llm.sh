#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
STATE_DIR="${REPO_DIR}/.local/ollama"
PID_FILE="${STATE_DIR}/server.pid"
LOG_FILE="${STATE_DIR}/server.log"

MODEL="${LLM_MODEL:-qwen3.5:9b}"
HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
CONTEXT_LENGTH="${LLM_MAX_CONTEXT:-16384}"
API_ROOT="http://${HOST}"

usage() {
  cat <<'EOF'
Usage: ./scripts/local-llm.sh <command>

Commands:
  demo      Install Ollama if needed, start it, pull the model, and run smoke test
  install   Install Ollama (macOS/Homebrew only)
  start     Start a project-managed Ollama server if none is already responding
  pull      Download LLM_MODEL (default: qwen3.5:9b)
  smoke     Test Traditional Chinese structured output through the OpenAI API
  status    Show server and model status
  logs      Follow the project-managed server log
  stop      Stop only the server started by this script

Environment:
  LLM_MODEL=qwen3.5:9b       Ollama model tag
  LLM_MAX_CONTEXT=16384      Context window exposed by the local server
  OLLAMA_HOST=127.0.0.1:11434
EOF
}

have_ollama() {
  command -v ollama >/dev/null 2>&1
}

server_ready() {
  curl --silent --fail --max-time 2 "${API_ROOT}/api/tags" >/dev/null 2>&1
}

install_ollama() {
  if have_ollama; then
    echo "Ollama is already installed: $(ollama --version 2>/dev/null || true)"
    return
  fi

  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Automatic installation is only enabled for macOS." >&2
    echo "Install Ollama from https://docs.ollama.com/ and rerun this command." >&2
    exit 1
  fi
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required for automatic installation: https://brew.sh/" >&2
    exit 1
  fi

  HOMEBREW_NO_AUTO_UPDATE=1 brew install ollama
}

start_server() {
  have_ollama || {
    echo "Ollama is not installed. Run '$0 install' first." >&2
    exit 1
  }
  if server_ready; then
    echo "Using the Ollama server already listening at ${API_ROOT}."
    return
  fi

  mkdir -p "${STATE_DIR}"
  OLLAMA_HOST="${HOST}" OLLAMA_CONTEXT_LENGTH="${CONTEXT_LENGTH}" \
    nohup ollama serve >"${LOG_FILE}" 2>&1 &
  local server_pid=$!
  echo "${server_pid}" >"${PID_FILE}"

  for _ in {1..30}; do
    if server_ready; then
      echo "Started Ollama (PID ${server_pid}, context ${CONTEXT_LENGTH}) at ${API_ROOT}."
      return
    fi
    if ! kill -0 "${server_pid}" 2>/dev/null; then
      echo "Ollama exited before becoming ready. See ${LOG_FILE}." >&2
      exit 1
    fi
    sleep 1
  done
  echo "Timed out waiting for Ollama. See ${LOG_FILE}." >&2
  exit 1
}

pull_model() {
  server_ready || start_server
  echo "Ensuring model is available: ${MODEL}"
  OLLAMA_HOST="${HOST}" ollama pull "${MODEL}"
}

smoke_test() {
  server_ready || {
    echo "Ollama is not responding at ${API_ROOT}. Run '$0 start' first." >&2
    exit 1
  }
  LLM_BASE_URL="${API_ROOT}/v1" LLM_MODEL="${MODEL}" \
    python3 "${SCRIPT_DIR}/llm_smoke_test.py"
}

show_status() {
  if server_ready; then
    echo "Server: ready (${API_ROOT})"
    OLLAMA_HOST="${HOST}" ollama list
  else
    echo "Server: stopped or unreachable (${API_ROOT})"
    return 1
  fi
}

stop_server() {
  if [[ ! -f "${PID_FILE}" ]]; then
    echo "No project-managed PID file found; nothing was stopped."
    return
  fi
  local server_pid
  server_pid="$(<"${PID_FILE}")"
  if [[ "${server_pid}" =~ ^[0-9]+$ ]] && kill -0 "${server_pid}" 2>/dev/null; then
    local process_command
    process_command="$(ps -p "${server_pid}" -o command= 2>/dev/null || true)"
    if [[ "${process_command}" == *"ollama serve"* ]]; then
      kill "${server_pid}"
      echo "Stopped project-managed Ollama server (PID ${server_pid})."
    else
      echo "PID ${server_pid} no longer belongs to 'ollama serve'; nothing was stopped." >&2
    fi
  else
    echo "Recorded server PID ${server_pid} is no longer running."
  fi
  rm -f "${PID_FILE}"
}

command_name="${1:-demo}"
case "${command_name}" in
  demo)
    install_ollama
    start_server
    pull_model
    smoke_test
    ;;
  install) install_ollama ;;
  start) start_server ;;
  pull) pull_model ;;
  smoke) smoke_test ;;
  status) show_status ;;
  logs)
    [[ -f "${LOG_FILE}" ]] || { echo "No log file at ${LOG_FILE}." >&2; exit 1; }
    tail -f "${LOG_FILE}"
    ;;
  stop) stop_server ;;
  help|-h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
