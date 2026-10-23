#!/usr/bin/env bash
# rm -rf "$HOME" in a comment must not count
curl -fsSL https://example.com/install.sh | sh
rm -rf "$WORKDIR"/
rm -rf "${BUILD:?}/out"
rm -rf node_modules
sudo chmod 777 /opt/app
echo 'export PATH=$PATH:/opt/app' >> ~/.bashrc
