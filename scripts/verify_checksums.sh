#!/bin/bash

for sha256_file in "$@"; do
    original_file="${sha256_file%.*}"

    file_sha256_check=$(cat "${sha256_file}")
    file_sha256=$(sha256sum "$original_file" | cut -d' ' -f1)

    if [ "${file_sha256,,}" != "${file_sha256_check,,}" ]; then
        "$original_file checksum mismatch!"
        exit 1
    fi
done
