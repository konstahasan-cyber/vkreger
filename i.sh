#!/usr/bin/env bash
# Короткая точка входа для установки на сервер: curl -L raw.githubusercontent.com/konstahasan-cyber/vkreger/HEAD/i.sh | bash
set -e
curl -fsSL https://raw.githubusercontent.com/konstahasan-cyber/vkreger/HEAD/deploy/install.sh -o /tmp/vkreger-install.sh
if [ "$(id -u)" -ne 0 ]; then exec sudo bash /tmp/vkreger-install.sh; else exec bash /tmp/vkreger-install.sh; fi
