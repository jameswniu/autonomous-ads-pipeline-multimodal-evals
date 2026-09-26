# switches.sh: where shoots/build-ad.sh mixes hit2.mp3, the switching sound. Sourced by the build, never run.
#
# switch_hits <mode> <t2_ms> <t3_ms> <video> <card_s> sets four variables for the audio mix:
#   KHITS       the filter lines that delay hit2 to each time, one per hit
#   KLABELS     their output labels, in order, for the amix
#   NK          how many there are
#   SWITCHLINE  the line the build prints for the ledger, empty when the board left the mode unset
# The modes, from a board's "switches":
#   slots  under the narration's second and third sentences, where the August builds cut from one
#          scene to the next. An empty mode is this too, the default, and exactly the mix the build
#          made before this existed, down to printing nothing extra.
#   off    nowhere
#   cuts   where the assembled picture changes most, found by switch_times.py beside this file
switch_hits() {
  local mode=$1 t2=$2 t3=$3 video=$4 card=$5 at s ms
  KHITS=""; KLABELS=""; NK=0; SWITCHLINE=""
  case $mode in
    ''|slots)
      KHITS="[6:a]adelay=$t2|$t2,volume=0.4[k1];[6:a]adelay=$t3|$t3,volume=0.4[k2];"; KLABELS="[k1][k2]"; NK=2
      [ -z "$mode" ] || SWITCHLINE="SWITCHES mode=slots at=$(echo "scale=2; $t2/1000" | bc),$(echo "scale=2; $t3/1000" | bc)" ;;
    off)
      SWITCHLINE="SWITCHES mode=off at=" ;;
    cuts)
      SWITCHLINE=$(python3 "$(dirname "${BASH_SOURCE[0]}")/switch_times.py" "$video" "$card" | tail -1)
      at=${SWITCHLINE#"SWITCHES mode=cuts at="}
      if [ "$at" = "$SWITCHLINE" ]; then
        echo "switch_times.py printed no machine line for $video" >&2; return 3
      fi
      for s in ${at//,/ }; do
        NK=$((NK + 1)); ms=$(echo "$s*1000/1" | bc)
        KHITS="$KHITS[6:a]adelay=$ms|$ms,volume=0.4[k$NK];"; KLABELS="$KLABELS[k$NK]"
      done ;;
    *)
      echo "SWITCHES must be slots, off or cuts, not '$mode'" >&2; return 2 ;;
  esac
}
