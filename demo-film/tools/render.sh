#!/bin/sh
# Renders the film and masters its sound.
#   sh tools/render.sh            ->  film/out/pramana-film.mp4 (1920x1080, 30 fps) and .srt
#   SCALE=1.3333333333333333 NAME=pramana-film-1440p sh tools/render.sh   ->  the same film at 2560x1440
#   (the screen takes are recorded at 3072x1728, so the larger frame holds real detail)
# Steps: timeline + subtitles, music bed, Remotion render, then one ffmpeg pass that brings
# the programme loudness to -16 LUFS (true peak -1.5 dB) without touching the picture.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
FILM="$HERE/../film"
KIT="${PRAMANA_MEDIA_KIT:?set PRAMANA_MEDIA_KIT to the media kit folder (see tools/voice.py)}/media-venv"
FFMPEG="${FFMPEG:-ffmpeg}"
SCALE="${SCALE:-1}"
NAME="${NAME:-pramana-film}"

cd "$FILM"
node "$HERE/timeline.mjs" 2>/dev/null
"$KIT/bin/python" "$HERE/music.py"
./node_modules/.bin/remotion render src/index.ts Film "out/picture-$NAME.mp4" --concurrency="${CONCURRENCY:-6}" --crf=17 --color-space=bt709 --scale="$SCALE" --log=error
"$FFMPEG" -y -loglevel error -i "out/picture-$NAME.mp4" -c:v copy -af "loudnorm=I=-16:TP=-1.5:LRA=11" -c:a aac -b:a 256k -ar 48000 -movflags +faststart "out/$NAME.mp4"
rm -f "out/picture-$NAME.mp4"
ls -la "out/$NAME.mp4" out/pramana-film.srt
