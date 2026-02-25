#!/bin/bash
# Apply or remove the "forward port missing" label on PRs based on the JSON input.

set -eu

main() {
    if [ "$#" -ne 1 ]; then echo "Usage: $0 <results.json>"; exit 1; fi
    # support both GITHUB_TOKEN and GH_TOKEN for flexibility. `gh` expects GH_TOKEN
    GH_TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
    command -v gh >/dev/null 2>&1 || { echo >&2 "gh is required but it's not installed. Aborting."; exit 1; }
    command -v jq >/dev/null 2>&1 || { echo >&2 "jq is required but it's not installed. Aborting."; exit 1; }

    jq -c '.[]' "$1" | while read -r pr; do
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
            gh pr edit "$number" --add-label "forward port missing"
        elif [ "$forward_ported" = true ] && [ "$label" = true ]; then
            echo "  Removing the 'forward port missing' label."
            gh pr edit "$number" --remove-label "forward port missing"
        else
            echo "  No label changes needed."
        fi

    done
}

main "$1"
