#!/bin/bash
# Apply or remove the "forward port missing" label on PRs based on the JSON input.

set -eu

DRY_RUN=false
INPUT=""

help() {
    cat <<'EOF'
Usage: apply_pr_labels.sh [options] results.json

Arguments:
  results.json     Path to the forward-port-missing JSON report.

Options:
  -n, --dry-run    Print commands instead of invoking gh.
  -h, --help       Show this message and exit.
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -n|--dry-run) DRY_RUN=true; shift ;;
            -h|--help)    help; exit 0 ;;
            *)            break ;;
        esac
    done
    if [[ $# -ne 1 ]]; then help; exit 1; fi
    INPUT=$1
}

main() {
    local results_path="$1"

    if [ "$DRY_RUN" = false ]; then
        test -z "$GH_TOKEN" && { echo "GH_TOKEN is not set. Aborting."; exit 1; }
        command -v gh >/dev/null 2>&1 || { echo >&2 "gh is required but it's not installed. Aborting."; exit 1; }
    fi
    command -v jq >/dev/null 2>&1 || { echo >&2 "jq is required but it's not installed. Aborting."; exit 1; }

    jq -c '.[]' "$results_path" | while read -r pr; do
        local number=$(echo "$pr" | jq -r '.number')
        local title=$(echo "$pr" | jq -r '.title')
        local url=$(echo "$pr" | jq -r '.url')
        local base=$(echo "$pr" | jq -r '.base')
        local head=$(echo "$pr" | jq -r '.head')
        local forward_ported=$(echo "$pr" | jq -r '.forward_ported')
        local label=$(echo "$pr" | jq -r '.label')

        echo "PR #$number: $title"
        echo "  $head -> $base"
        echo "  $url"

        if [ "$forward_ported" = false ] && [ "$label" = false ]; then
            echo "  Adding the 'forward port missing' label."
            if [ "$DRY_RUN" = true ]; then
                echo "> gh pr edit $number --add-label \"forward port missing\""
            else
                gh pr edit "$number" --add-label "forward port missing"
            fi
        elif [ "$forward_ported" = true ] && [ "$label" = true ]; then
            echo "  Removing the 'forward port missing' label."
            if [ "$DRY_RUN" = true ]; then
                echo "> gh pr edit $number --remove-label \"forward port missing\""
            else
                gh pr edit "$number" --remove-label "forward port missing"
            fi
        else
            echo "  No label changes needed."
        fi

    done
}

parse_args "$@"
main "$INPUT"