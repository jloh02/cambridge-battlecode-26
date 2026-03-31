#!/bin/bash

# ==============================================================================
# CONFIGURATION & SETUP
# ==============================================================================
if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <my_bot> <opponent_bot> [maps_dir]"
    echo "Example: $0 my_bot starter maps"
    exit 1
fi

MY_BOT=$1
OPPONENT=$2
MAPS_DIR=${3:-maps}

MY_NAME=$(basename "$MY_BOT")
OPP_NAME=$(basename "$OPPONENT")

# USE ABSOLUTE PATHS to prevent background workers from getting lost
LOG_DIR="$PWD/logs"
STATUS_DIR="$PWD/.match_status"
TASK_LIST="$PWD/.tasks.txt"
WORKER_SCRIPT="$PWD/.worker.sh"

MAX_CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

if [ ! -d "$MAPS_DIR" ]; then
    echo "Error: Maps directory '$MAPS_DIR' not found."
    exit 1
fi

rm -rf "$LOG_DIR" "$STATUS_DIR" "$TASK_LIST" "$WORKER_SCRIPT"
mkdir -p "$LOG_DIR" "$STATUS_DIR"

# ==============================================================================
# WORKER SCRIPT GENERATION
# ==============================================================================
cat << 'EOF' > "$WORKER_SCRIPT"
#!/bin/bash
team_a=$1
team_b=$2
map_file=$3
match_id=$4
LOG_DIR=$5
STATUS_DIR=$6

echo "RUNNING" > "$STATUS_DIR/$match_id"

# 1. Attempt to create the file and catch any OS-level File System errors
if ! touch "$LOG_DIR/${match_id}.log" 2>/dev/null; then
    echo "FAILED (FS Error)" > "$STATUS_DIR/$match_id"
    exit 1
fi

# Force Python to flush output immediately
export PYTHONUNBUFFERED=1

# 2. Run the engine, save the replay, and capture the exit code
cambc run "$team_a" "$team_b" "$map_file" --replay "$LOG_DIR/${match_id}.replay26" > "$LOG_DIR/${match_id}.log" 2>&1
EXIT_CODE=$?

sleep 0.5

# 3. Safely check for the winner
if [ -f "$LOG_DIR/${match_id}.log" ]; then
    if [ $EXIT_CODE -eq 0 ]; then
        winner=$(grep -i "Winner:" "$LOG_DIR/${match_id}.log" | tail -n 1 | sed 's/.*Winner: //')
        if [ -n "$winner" ]; then
            echo "DONE ($winner)" > "$STATUS_DIR/$match_id"
        else
            echo "DONE (Unknown)" > "$STATUS_DIR/$match_id"
        fi
    else
        echo "FAILED (Exit $EXIT_CODE)" > "$STATUS_DIR/$match_id"
    fi
else
    # We should theoretically never hit this now because of the FS Error check above
    echo "FAILED (Missing Log)" > "$STATUS_DIR/$match_id"
fi
EOF
chmod +x "$WORKER_SCRIPT"

# ==============================================================================
# QUEUE GENERATION
# ==============================================================================
declare -a MATCH_IDS

for map_file in "$MAPS_DIR"/*.map26; do
    [ -e "$map_file" ] || { echo "No .map26 files found in $MAPS_DIR."; exit 1; }

    # Extract the raw map name
    raw_map_name=$(basename "$map_file" .map26)

    # SANITIZE: Replace spaces and weird characters with underscores
    safe_map_name=$(echo "$raw_map_name" | sed 's/[^a-zA-Z0-9_-]/_/g')

    # Queue Match 1 (Your Bot is Team A) - Removed parentheses from the ID
    match1_id="${safe_map_name}_A"
    echo "PENDING" > "$STATUS_DIR/$match1_id"
    MATCH_IDS+=("$match1_id")
    printf "%s\0%s\0%s\0%s\0%s\0%s\0" "$MY_BOT" "$OPPONENT" "$map_file" "$match1_id" "$LOG_DIR" "$STATUS_DIR" >> "$TASK_LIST"

    # Queue Match 2 (Your Bot is Team B) - Removed parentheses from the ID
    match2_id="${safe_map_name}_B"
    echo "PENDING" > "$STATUS_DIR/$match2_id"
    MATCH_IDS+=("$match2_id")
    printf "%s\0%s\0%s\0%s\0%s\0%s\0" "$OPPONENT" "$MY_BOT" "$map_file" "$match2_id" "$LOG_DIR" "$STATUS_DIR" >> "$TASK_LIST"
done

# ==============================================================================
# EXECUTION & 3-COLUMN DASHBOARD
# ==============================================================================
xargs -0 -n 6 -P "$MAX_CORES" "$WORKER_SCRIPT" < "$TASK_LIST" &
XARGS_PID=$!

clear
while kill -0 $XARGS_PID 2>/dev/null; do
    tput cup 0 0

    # 1. Tally Wins
    my_wins=0
    opp_wins=0
    other_results=0

    for match_id in "${MATCH_IDS[@]}"; do
        stat=$(cat "$STATUS_DIR/$match_id" 2>/dev/null || echo "PENDING")
        if [[ "$stat" == *"DONE"* ]]; then
            if [[ "$stat" == *"$MY_NAME"* ]]; then
                ((my_wins++))
            elif [[ "$stat" == *"$OPP_NAME"* ]]; then
                ((opp_wins++))
            elif [[ "$stat" == *"Team A"* || "$stat" == *"team_a"* ]]; then
                if [[ "$match_id" == *"_A" ]]; then ((my_wins++)); else ((opp_wins++)); fi
            elif [[ "$stat" == *"Team B"* || "$stat" == *"team_b"* ]]; then
                if [[ "$match_id" == *"_A" ]]; then ((opp_wins++)); else ((my_wins++)); fi
            else
                ((other_results++))
            fi
        elif [[ "$stat" == *"FAILED"* ]]; then
            ((other_results++))
        fi
    done

    # 2. Draw Dashboard Header
    echo "======================================================================================================================="
    echo " BATTLECODE LOCAL TOURNAMENT DASHBOARD"
    echo " Contenders : $MY_NAME vs $OPP_NAME"
    echo " Scoreboard : $MY_NAME -> $my_wins wins  |  $OPP_NAME -> $opp_wins wins  |  Ties/Errors -> $other_results"
    echo " Concurrency: $MAX_CORES parallel matches"
    echo "======================================================================================================================="
    printf "%-22s | %-12s || %-22s | %-12s || %-22s | %-12s\n" "MATCH (Your Side)" "STATUS" "MATCH (Your Side)" "STATUS" "MATCH (Your Side)" "STATUS"
    echo "-----------------------+--------------||------------------------+--------------||------------------------+--------------"

    # 3. Draw 3 Columns
    for (( i=0; i<${#MATCH_IDS[@]}; i+=3 )); do

        # --- COLUMN 1 ---
        match1="${MATCH_IDS[i]}"
        stat1=$(cat "$STATUS_DIR/$match1" 2>/dev/null || echo "PENDING")
        printf -v m1_pad "%-22s" "${match1:0:22}"
        printf -v s1_pad "%-12s" "${stat1:0:12}"

        if [[ "$stat1" == *"RUNNING"* ]]; then s1_c="\033[33m${s1_pad}\033[0m"
        elif [[ "$stat1" == *"DONE"* ]]; then s1_c="\033[32m${s1_pad}\033[0m"
        elif [[ "$stat1" == *"FAILED"* ]]; then s1_c="\033[31m${s1_pad}\033[0m"
        else s1_c="${s1_pad}"
        fi

        # --- COLUMN 2 ---
        if (( i+1 < ${#MATCH_IDS[@]} )); then
            match2="${MATCH_IDS[i+1]}"
            stat2=$(cat "$STATUS_DIR/$match2" 2>/dev/null || echo "PENDING")
            printf -v m2_pad "%-22s" "${match2:0:22}"
            printf -v s2_pad "%-12s" "${stat2:0:12}"

            if [[ "$stat2" == *"RUNNING"* ]]; then s2_c="\033[33m${s2_pad}\033[0m"
            elif [[ "$stat2" == *"DONE"* ]]; then s2_c="\033[32m${s2_pad}\033[0m"
            elif [[ "$stat2" == *"FAILED"* ]]; then s2_c="\033[31m${s2_pad}\033[0m"
            else s2_c="${s2_pad}"
            fi
        else
            m2_pad="                      "
            s2_c="            "
        fi

        # --- COLUMN 3 ---
        if (( i+2 < ${#MATCH_IDS[@]} )); then
            match3="${MATCH_IDS[i+2]}"
            stat3=$(cat "$STATUS_DIR/$match3" 2>/dev/null || echo "PENDING")
            printf -v m3_pad "%-22s" "${match3:0:22}"
            printf -v s3_pad "%-12s" "${stat3:0:12}"

            if [[ "$stat3" == *"RUNNING"* ]]; then s3_c="\033[33m${s3_pad}\033[0m"
            elif [[ "$stat3" == *"DONE"* ]]; then s3_c="\033[32m${s3_pad}\033[0m"
            elif [[ "$stat3" == *"FAILED"* ]]; then s3_c="\033[31m${s3_pad}\033[0m"
            else s3_c="${s3_pad}"
            fi
        else
            m3_pad="                      "
            s3_c="            "
        fi

        printf "%s | %b || %s | %b || %s | %b\n" "$m1_pad" "$s1_c" "$m2_pad" "$s2_c" "$m3_pad" "$s3_c"
    done

    tput ed
    sleep 1
done

# ==============================================================================
# FINAL CLEANUP
# ==============================================================================
rm -f "$WORKER_SCRIPT" "$TASK_LIST"
rm -rf "$STATUS_DIR"

echo "-----------------------+--------------||------------------------+--------------||------------------------+--------------"
echo ""
echo "Tournament Complete! Final Score -> $MY_NAME: $my_wins | $OPP_NAME: $opp_wins"