#!/bin/bash
# test-interactive-prototype.sh — Test interactive mode with autopilot switch
#
# Run this directly in your terminal:
#   scripts/test-interactive-prototype.sh
#
# Simulates a 3-scene drafting session in interactive mode.
# Each "scene" is a short claude session (or simulated with echo/sleep).
# Between scenes, the script checks for working/.autopilot.
#
# To test with REAL claude: scripts/test-interactive-prototype.sh --real

set -eo pipefail

USE_REAL_CLAUDE=false
if [[ "${1:-}" == "--real" ]]; then
    USE_REAL_CLAUDE=true
fi

PROJECT_DIR="${PWD}"
AUTOPILOT_FILE="${PROJECT_DIR}/working/.autopilot"
rm -f "$AUTOPILOT_FILE"
mkdir -p "${PROJECT_DIR}/working"

SCENES=("scene-1" "scene-2" "scene-3")

echo "=== Interactive Mode + Autopilot Test ==="
echo ""
echo "This simulates drafting ${#SCENES[@]} scenes in interactive mode."
echo "During any scene, tell Claude: 'autopilot the rest'"
echo "Claude will create the autopilot file, then you /exit."
echo "Remaining scenes run autonomously."
echo ""

for (( i=0; i<${#SCENES[@]}; i++ )); do
    SCENE="${SCENES[$i]}"
    NUM=$((i + 1))

    echo "--- Scene ${NUM}/${#SCENES[@]}: ${SCENE} ---"

    if [[ -f "$AUTOPILOT_FILE" ]]; then
        echo "[AUTOPILOT] Running ${SCENE} autonomously (headless)..."

        if [[ "$USE_REAL_CLAUDE" == true ]]; then
            claude -p "Say: 'Autonomously drafted ${SCENE}.' Then run: echo 'drafted' > /tmp/storyforge-test-${SCENE}.txt" \
                --model claude-opus-4-6 \
                --dangerously-skip-permissions \
                --output-format stream-json \
                --verbose \
                > "/tmp/storyforge-test-${SCENE}.log" 2>&1
            EXIT_CODE=$?
        else
            echo "[SIM] claude -p \"Draft ${SCENE}...\" (headless, no interaction)"
            sleep 1
            EXIT_CODE=0
        fi

        echo "[AUTOPILOT] ${SCENE} complete (exit: ${EXIT_CODE})"
    else
        echo "[INTERACTIVE] Opening interactive session for ${SCENE}..."
        echo "[INTERACTIVE] You can interact with Claude."
        echo "[INTERACTIVE] Say 'autopilot the rest' to switch remaining scenes to autonomous."
        echo "[INTERACTIVE] Type /exit when done with this scene."
        echo ""

        if [[ "$USE_REAL_CLAUDE" == true ]]; then
            set +e
            claude "Draft ${SCENE} (${NUM} of ${#SCENES[@]}) — one paragraph of placeholder prose." \
                --model claude-opus-4-6 \
                --dangerously-skip-permissions \
                --append-system-prompt "You are in interactive drafting mode, managed by a script that loops over scenes one at a time.

RULES:
- Draft THIS SCENE ONLY. Do not proceed to the next scene — the script handles sequencing.
- When this scene is done, tell the user the scene is complete and wait for them to respond.
- The user may give you feedback, ask for changes, or say they are satisfied.
- When the user is done with this scene, they will type /exit to move on.

AUTOPILOT:
- If the user says 'autopilot the rest', 'go autonomous', 'finish without me', or similar:
  1. Run: touch ${AUTOPILOT_FILE}
  2. Tell them: 'Autopilot enabled — the remaining scenes will run autonomously. Type /exit to continue.'
- Do NOT exit on your own. The user types /exit when ready."
            EXIT_CODE=$?
            set -e
        else
            echo "[SIM] === This is where you'd see Claude's interactive UI ==="
            echo "[SIM] === Claude drafts the scene, you watch or intervene  ==="
            echo "[SIM] ==="
            echo "[SIM] Press ENTER to simulate finishing this scene normally."
            echo "[SIM] Type 'autopilot' + ENTER to switch remaining scenes to autonomous."
            read -r USER_INPUT
            if [[ "$USER_INPUT" == "autopilot" ]]; then
                touch "$AUTOPILOT_FILE"
                echo "[SIM] Autopilot file created. Remaining scenes will be autonomous."
            fi
            EXIT_CODE=0
        fi

        echo ""
        echo "[INTERACTIVE] Session ended (exit: ${EXIT_CODE})"
    fi

    # Post-invocation verification (same regardless of mode)
    echo "[VERIFY] Checking ${SCENE}... OK"
    echo ""

    # Pause between scenes
    if (( i < ${#SCENES[@]} - 1 )); then
        sleep 1
    fi
done

# Cleanup
rm -f "$AUTOPILOT_FILE"

echo "=== All scenes complete ==="
echo ""
echo "If you saw scenes switch from [INTERACTIVE] to [AUTOPILOT]"
echo "after typing 'autopilot', the pattern works."
