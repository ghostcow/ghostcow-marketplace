#!/bin/bash

# Read JSON input
input=$(cat)

# ── Colors ──────────────────────────────────────
c_pink='\033[38;5;213m'
c_purple='\033[38;5;147m'
c_blue='\033[38;5;111m'
c_lavender='\033[38;5;183m'
c_teal='\033[38;5;109m'
c_reset='\033[0m'

# ── Input parsing ───────────────────────────────
{ read -r model; read -r current_dir; read -r remaining_pct; } < <(
    echo "$input" | jq -r '
        (.model.display_name // "Claude"),
        .workspace.current_dir,
        (.context_window.remaining_percentage // "")
    '
)
dir=$(basename "$current_dir")

# Show git branch only when current_dir is inside a repo
branch=$(git -C "$current_dir" branch --show-current 2>/dev/null)

# ── Cat face ────────────────────────────────────
sec=$(($(date +%S) % 20))
case $sec in
    0) face='(=^‥^=)';;      # Classic cat
    1) face='(=◕ᴥ◕=)';;      # Bear-cat
    2) face='(=◡ ω ◡=)';;    # Happy cat
    3) face='(=｡◕‿◕｡=)';;   # Cute cat
    4) face='(=⌐■_■=)';;     # Cool cat
    5) face='(=✧ω✧=)';;     # Sparkle cat
    6) face='(=♡‿♡=)';;      # Love cat
    7) face='(=°◡°=)';;      # Pleased cat
    8) face='(=◉ᴥ◉=)';;     # Wide-eyed cat
    9) face='(=^◡^=)';;      # Smiling cat
    10) face='(=ಠᴥಠ=)';;    # Judging cat
    11) face='(=≧ ω≦=)';;   # Excited cat
    12) face='(=´∇｀=)';;    # Grinning cat
    13) face='(=ᵔᴥᵔ=)';;    # Curious cat
    14) face='(=^・ω・^=)';; # Whisker cat
    15) face='(=◕ ‿‿ ◕=)';; # Derp cat
    16) face='(=✿◠‿◠=)';;   # Flower cat
    17) face='(=╹ᆺ╹=)';;    # Alert cat
    18) face='(=^∇^=)';;     # Joy cat
    19) face='(=◠ᴥ◠=)';;    # Gentle cat
esac

# ── Output formatting ──────────────────────────
branch_seg=""
if [ -n "$branch" ]; then
    branch_seg=$(printf " ${c_lavender}→ %s${c_reset}" "$branch")
fi

ctx=""
if [ -n "$remaining_pct" ]; then
    ctx=$(printf " ${c_teal}remaining context: %d%%${c_reset}" "$remaining_pct")
fi

printf "${c_pink}%s${c_reset} ${c_purple}%s${c_reset} ${c_blue}@ %s${c_reset}%s%s" \
    "$face" "$model" "$dir" "$branch_seg" "$ctx"
