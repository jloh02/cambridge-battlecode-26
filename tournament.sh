#!/bin/sh

set -u

usage() {
    cat <<'EOF'
Usage:
  tournament.sh <my_bot> <opponent_bot> [maps_dir]
  tournament.sh <my_bot> <opponent1> [opponent2 ...] [--maps-dir DIR] [--seeds 1,7,13] [--jobs N] [--output FILE]

Notes:
  - Preserves the original 3-column live dashboard.
  - Runs both seat orders for every opponent/map/seed combination.
  - Uses benchmark_matrix.py as the execution/replay-analysis/report backend.
  - POSIX-sh friendly: works under sh, dash, and zsh without Bash-only features.
EOF
}

if [ "$#" -lt 2 ]; then
    usage
    exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MY_BOT=$1
shift

TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/tournament.XXXXXX") || exit 1
POSITIONALS_FILE="$TMP_ROOT/positionals.txt"
SEEDS_FILE="$TMP_ROOT/seeds.txt"
OPPONENTS_FILE="$TMP_ROOT/opponents.txt"
EVENTS_FILE="$TMP_ROOT/events.log"
BACKEND_ERR_FILE="$TMP_ROOT/backend.stderr"
: > "$POSITIONALS_FILE"
: > "$SEEDS_FILE"
: > "$EVENTS_FILE"
: > "$BACKEND_ERR_FILE"

cleanup() {
    if [ "${BACKEND_PID:-}" != "" ]; then
        kill "$BACKEND_PID" 2>/dev/null || true
    fi
    rm -rf "$TMP_ROOT"
}

trap 'cleanup' EXIT HUP INT TERM

MAPS_DIR=""
MAPS_DIR_SET=0
SEEDS_CSV="1"
JOBS=""
OUTPUT=""
PYTHON_BIN=""
BACKEND_PATH=""
REFRESH_SECS="0.20"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --maps-dir)
            [ "$#" -ge 2 ] || { echo "Missing value for --maps-dir" >&2; exit 1; }
            MAPS_DIR=$2
            MAPS_DIR_SET=1
            shift 2
            ;;
        --seeds)
            [ "$#" -ge 2 ] || { echo "Missing value for --seeds" >&2; exit 1; }
            SEEDS_CSV=$2
            shift 2
            ;;
        --jobs)
            [ "$#" -ge 2 ] || { echo "Missing value for --jobs" >&2; exit 1; }
            JOBS=$2
            shift 2
            ;;
        --output)
            [ "$#" -ge 2 ] || { echo "Missing value for --output" >&2; exit 1; }
            OUTPUT=$2
            shift 2
            ;;
        --python)
            [ "$#" -ge 2 ] || { echo "Missing value for --python" >&2; exit 1; }
            PYTHON_BIN=$2
            shift 2
            ;;
        --backend)
            [ "$#" -ge 2 ] || { echo "Missing value for --backend" >&2; exit 1; }
            BACKEND_PATH=$2
            shift 2
            ;;
        --refresh)
            [ "$#" -ge 2 ] || { echo "Missing value for --refresh" >&2; exit 1; }
            REFRESH_SECS=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            while [ "$#" -gt 0 ]; do
                printf '%s\n' "$1" >> "$POSITIONALS_FILE"
                shift
            done
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            printf '%s\n' "$1" >> "$POSITIONALS_FILE"
            shift
            ;;
    esac
done

positional_count=$(wc -l < "$POSITIONALS_FILE" | tr -d ' ')
if [ "$positional_count" -lt 1 ]; then
    usage
    exit 1
fi

if [ "$MAPS_DIR_SET" -eq 0 ] && [ "$positional_count" -ge 2 ]; then
    last_value=$(tail -n 1 "$POSITIONALS_FILE")
    if [ -d "$last_value" ]; then
        MAPS_DIR=$last_value
        sed '$d' "$POSITIONALS_FILE" > "$TMP_ROOT/positionals.next"
        mv "$TMP_ROOT/positionals.next" "$POSITIONALS_FILE"
        positional_count=$(wc -l < "$POSITIONALS_FILE" | tr -d ' ')
    fi
fi

if [ -z "$MAPS_DIR" ]; then
    MAPS_DIR="maps"
fi

if [ "$positional_count" -lt 1 ]; then
    echo "At least one opponent is required." >&2
    exit 1
fi

cp "$POSITIONALS_FILE" "$OPPONENTS_FILE"
opponent_count=$(wc -l < "$OPPONENTS_FILE" | tr -d ' ')

MY_NAME=$(basename "$MY_BOT")
if [ "$opponent_count" -eq 1 ]; then
    first_opponent=$(head -n 1 "$OPPONENTS_FILE")
    FIELD_NAME=$(basename "$first_opponent")
else
    FIELD_NAME="field($opponent_count)"
fi

OPPONENTS_DISPLAY=$(paste -sd ' ' "$OPPONENTS_FILE" 2>/dev/null)
if [ -z "$OPPONENTS_DISPLAY" ]; then
    OPPONENTS_DISPLAY=$(tr '\n' ' ' < "$OPPONENTS_FILE" | sed 's/[[:space:]]*$//')
fi

if [ -z "$PYTHON_BIN" ]; then
    if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
        PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN=$(command -v python3)
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN=$(command -v python)
    else
        echo "Error: python3/python not found." >&2
        exit 1
    fi
fi

if [ -z "$BACKEND_PATH" ]; then
    if [ -f "$SCRIPT_DIR/tools/benchmark_matrix.py" ]; then
        BACKEND_PATH="$SCRIPT_DIR/tools/benchmark_matrix.py"
    elif [ -f "$SCRIPT_DIR/benchmark_matrix.py" ]; then
        BACKEND_PATH="$SCRIPT_DIR/benchmark_matrix.py"
    else
        echo "Error: benchmark_matrix.py not found. Use --backend to point at it." >&2
        exit 1
    fi
fi

if [ ! -f "$BACKEND_PATH" ]; then
    echo "Error: backend '$BACKEND_PATH' not found." >&2
    exit 1
fi

if [ ! -d "$MAPS_DIR" ] && [ ! -d "$SCRIPT_DIR/$MAPS_DIR" ]; then
    echo "Error: maps directory '$MAPS_DIR' not found." >&2
    exit 1
fi

printf '%s\n' "$SEEDS_CSV" | tr ',' '\n' | sed '/^$/d' > "$SEEDS_FILE"
if [ ! -s "$SEEDS_FILE" ]; then
    printf '1\n' > "$SEEDS_FILE"
fi
while IFS= read -r seed; do
    case "$seed" in
        *[!0-9]*|'')
            echo "Error: invalid seed '$seed'. Use comma-separated non-negative integers." >&2
            exit 1
            ;;
    esac
done < "$SEEDS_FILE"

render_dashboard() {
    awk \
        -v my_name="$MY_NAME" \
        -v field_name="$FIELD_NAME" \
        -v opponents_display="$OPPONENTS_DISPLAY" \
        '
        function truncpad(s, width,    out) {
            out = substr(s, 1, width)
            return sprintf("%-" width "s", out)
        }
        function colorize(text, status,    esc) {
            esc = sprintf("%c", 27)
            if (status ~ /^RUNNING/) return esc "[33m" text esc "[0m"
            if (status ~ /^DONE/)    return esc "[32m" text esc "[0m"
            if (status ~ /^FAILED/)  return esc "[31m" text esc "[0m"
            return text
        }
        BEGIN {
            FS = "\t"
            total_games = 0
            jobs_effective = "auto"
            report_path = "pending"
            queue_count = 0
            running_games = 0
            finished_games = 0
            my_wins = 0
            field_wins = 0
            other_results = 0
        }
        $1 == "META" {
            if ($3 != "") report_path = $3
            if ($4 != "") total_games = $4 + 0
            if ($5 != "") jobs_effective = $5
        }
        $1 == "QUEUE" {
            id = $2
            if (!(id in seen_queue)) {
                seen_queue[id] = 1
                queue_count += 1
                queue_order[queue_count] = id
            }
            labels[id] = $3
            status[id] = "PENDING"
            if (total_games == 0) total_games = queue_count
        }
        $1 == "START" {
            id = $2
            if (status[id] !~ /^RUNNING/ && status[id] !~ /^DONE/ && status[id] !~ /^FAILED/) {
                running_games += 1
            }
            status[id] = "RUNNING"
        }
        $1 == "DONE" {
            id = $2
            winner = $3
            if (status[id] ~ /^RUNNING/ && running_games > 0) running_games -= 1
            if (status[id] !~ /^DONE/ && status[id] !~ /^FAILED/) finished_games += 1
            status[id] = "DONE (" winner ")"
            if (winner == my_name) {
                my_wins += 1
            } else if (winner == "" || winner == "Draw") {
                other_results += 1
            } else {
                field_wins += 1
            }
        }
        $1 == "FAIL" {
            id = $2
            if (status[id] ~ /^RUNNING/ && running_games > 0) running_games -= 1
            if (status[id] !~ /^DONE/ && status[id] !~ /^FAILED/) finished_games += 1
            status[id] = "FAILED"
            other_results += 1
        }
        $1 == "REPORT" {
            if ($2 != "") report_path = $2
        }
        END {
            if (total_games == 0) total_games = queue_count
            print "======================================================================================================================="
            print " BATTLECODE LOCAL TOURNAMENT DASHBOARD"
            print " Contenders : " my_name " vs " field_name
            print " Scoreboard : " my_name " -> " my_wins " wins  |  " field_name " -> " field_wins " wins  |  Ties/Errors -> " other_results
            print " Progress    : " finished_games " / " total_games " complete  |  Running -> " running_games "  |  Concurrency -> " jobs_effective
            if (index(opponents_display, " ") > 0) {
                print " Opponents   : " opponents_display
            } else if (opponents_display != "") {
                print " Opponent    : " opponents_display
            } else {
                print " Opponent    : -"
            }
            print "======================================================================================================================="
            printf "%-22s | %-12s || %-22s | %-12s || %-22s | %-12s\n", "MATCH (Your Side)", "STATUS", "MATCH (Your Side)", "STATUS", "MATCH (Your Side)", "STATUS"
            print "-----------------------+--------------||------------------------+--------------||------------------------+--------------"

            for (i = 1; i <= queue_count; i += 3) {
                id1 = queue_order[i]
                lab1 = (id1 in labels ? labels[id1] : id1)
                st1 = (id1 in status ? status[id1] : "PENDING")
                m1 = truncpad(lab1, 22)
                s1 = colorize(truncpad(st1, 12), st1)

                if (i + 1 <= queue_count) {
                    id2 = queue_order[i + 1]
                    lab2 = (id2 in labels ? labels[id2] : id2)
                    st2 = (id2 in status ? status[id2] : "PENDING")
                    m2 = truncpad(lab2, 22)
                    s2 = colorize(truncpad(st2, 12), st2)
                } else {
                    m2 = "                      "
                    s2 = "            "
                }

                if (i + 2 <= queue_count) {
                    id3 = queue_order[i + 2]
                    lab3 = (id3 in labels ? labels[id3] : id3)
                    st3 = (id3 in status ? status[id3] : "PENDING")
                    m3 = truncpad(lab3, 22)
                    s3 = colorize(truncpad(st3, 12), st3)
                } else {
                    m3 = "                      "
                    s3 = "            "
                }

                printf "%s | %s || %s | %s || %s | %s\n", m1, s1, m2, s2, m3, s3
            }

            print ""
            print " Report      : " report_path
        }
        ' "$EVENTS_FILE"
}

backend_has_begun() {
    grep -q "^BEGIN" "$EVENTS_FILE" 2>/dev/null
}

backend_has_ended() {
    grep -q "^END" "$EVENTS_FILE" 2>/dev/null
}

extract_report_path() {
    awk -F '\t' '$1 == "REPORT" { path = $2 } $1 == "META" && path == "" { path = $3 } END { print path }' "$EVENTS_FILE"
}

set -- "$PYTHON_BIN" "$BACKEND_PATH" "$MY_BOT"
while IFS= read -r opponent; do
    set -- "$@" "$opponent"
done < "$OPPONENTS_FILE"
set -- "$@" --tournament-backend --tournament-maps-dir "$MAPS_DIR" --tournament-seeds
while IFS= read -r seed; do
    set -- "$@" "$seed"
done < "$SEEDS_FILE"
if [ -n "$JOBS" ]; then
    set -- "$@" --jobs "$JOBS"
fi
if [ -n "$OUTPUT" ]; then
    set -- "$@" --output "$OUTPUT"
fi

"$@" > "$EVENTS_FILE" 2> "$BACKEND_ERR_FILE" &
BACKEND_PID=$!

clear 2>/dev/null || printf '\033[2J\033[H'

while :; do
    if backend_has_begun; then
        break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        wait "$BACKEND_PID"
        status=$?
        echo "Backend exited before startup (status $status)." >&2
        if [ -s "$BACKEND_ERR_FILE" ]; then
            echo "---- backend stderr ----" >&2
            sed -n '1,120p' "$BACKEND_ERR_FILE" >&2
        fi
        exit "$status"
    fi
    sleep "$REFRESH_SECS"
done

render_dashboard

while :; do
    clear 2>/dev/null || printf '\033[2J\033[H'
    render_dashboard

    if backend_has_ended; then
        break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        break
    fi

    sleep "$REFRESH_SECS"
done

wait "$BACKEND_PID"
BACKEND_STATUS=$?
REPORT_PATH=$(extract_report_path)

clear 2>/dev/null || printf '\033[2J\033[H'
render_dashboard

echo "-----------------------+--------------||------------------------+--------------||------------------------+--------------"
echo ""

FINAL_SCORE=$(awk -v my_name="$MY_NAME" -v field_name="$FIELD_NAME" '
BEGIN { FS = "\t"; my = 0; field = 0; other = 0 }
$1 == "DONE" {
    if ($3 == my_name) my += 1
    else if ($3 == "" || $3 == "Draw") other += 1
    else field += 1
}
$1 == "FAIL" { other += 1 }
END { printf "%d\t%d\t%d\n", my, field, other }
' "$EVENTS_FILE")
FINAL_MY=$(printf '%s' "$FINAL_SCORE" | awk -F '\t' '{print $1}')
FINAL_FIELD=$(printf '%s' "$FINAL_SCORE" | awk -F '\t' '{print $2}')
FINAL_OTHER=$(printf '%s' "$FINAL_SCORE" | awk -F '\t' '{print $3}')

echo "Tournament Complete! Final Score -> $MY_NAME: $FINAL_MY | $FIELD_NAME: $FINAL_FIELD | Ties/Errors: $FINAL_OTHER"
if [ -n "$REPORT_PATH" ]; then
    echo "Report JSON -> $REPORT_PATH"
fi
if [ "$BACKEND_STATUS" -ne 0 ]; then
    echo "Backend exited with status $BACKEND_STATUS" >&2
    if [ -s "$BACKEND_ERR_FILE" ]; then
        echo "---- backend stderr ----" >&2
        sed -n '1,120p' "$BACKEND_ERR_FILE" >&2
    fi
    exit "$BACKEND_STATUS"
fi

if [ -n "$REPORT_PATH" ] && [ -f "$REPORT_PATH" ]; then
    "$PYTHON_BIN" - "$REPORT_PATH" <<'PY'
import json
import sys
from pathlib import Path

report_path = Path(sys.argv[1])
payload = json.loads(report_path.read_text(encoding="utf-8"))
summary = payload.get("summary", {})
print()
print("Benchmark-matrix summary")
print("------------------------")
print(
    f"Aggregate : {summary.get('aggregate_win_rate', 0.0):.1%} win rate over "
    f"{summary.get('games', 0)} completed games"
)
print(
    f"TiEq      : avg {summary.get('aggregate_tieq_avg', 0.0):.1f} | "
    f"worst {summary.get('aggregate_tieq_worst', 0)}"
)
print(
    f"Pathology : TLE turns {summary.get('candidate_tled_turns', 0)} | "
    f"small-loop games {summary.get('candidate_small_loop_games', 0)}"
)
for opponent, stats in sorted(summary.get("per_opponent", {}).items()):
    print(
        f"  {opponent}: {stats.get('wins', 0)}-{stats.get('losses', 0)} "
        f"({stats.get('draws', 0)} draws), avg TiEq {stats.get('candidate_tieq_avg', 0.0):.1f}"
    )
failures = payload.get("failures", [])
if failures:
    print(f"Failures   : {len(failures)}")
PY
fi
