#!/bin/sh
# usage: add_sfx.sh <sfx file> [start_sec=19.152] [out=telop_glow_sfx.mp4]
SFX="$1"; T="${2:-19.152}"; OUT="${3:-telop_glow_sfx.mp4}"
MS=$(python3 -c "print(int(round($T*1000)))")
ffmpeg -v error -y -i telop_glow.mp4 -i "$SFX" -filter_complex \
"[1:a]volume=-10dB,adelay=${MS}|${MS},aresample=48000,aformat=channel_layouts=stereo[s];\
[0:a][s]amix=inputs=2:duration=first:normalize=0[a]" \
-map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -movflags +faststart "$OUT"
