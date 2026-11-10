#!/bin/sh
# Records the README demo with asciinema (brew install asciinema), then converts it to a GIF
# with agg (brew install agg). Run it from a terminal that is about 100x28.
#
#   sh demo/record.sh
#
# While recording, do roughly this, slowly:
#   1. type:  seshpick      (the full list appears, newest first)
#   2. type:  tri           (the list narrows to names containing "tri", exact names first)
#   3. press: enter         (the session reopens in its own folder)
#   4. type:  /exit         (leave the resumed session), then  exit  to stop the recording
set -e
asciinema rec --overwrite --idle-time-limit 2 --title "seshpick" demo/seshpick.cast
agg --theme monokai --font-size 16 --cols 100 --rows 28 demo/seshpick.cast demo/seshpick.gif
echo "wrote demo/seshpick.gif"
