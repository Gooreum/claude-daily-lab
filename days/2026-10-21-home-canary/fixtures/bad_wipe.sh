#!/usr/bin/env bash
# 인자로 받은 폴더를 비운다. 가드가 없다 (사고 재현용 픽스처)
dir="$1"
rm -rf "$dir"/*
rm -rf "$dir"/.[!.]*
