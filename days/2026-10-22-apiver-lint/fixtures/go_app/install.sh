#!/usr/bin/env bash
go install 'github.com/anthropics/anthropic-cli/cmd/ant@latest'
ant completions create --model m --max-tokens-to-sample 10 --prompt "x"
