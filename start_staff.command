#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  print 'Set up the project first using README.md.'
  exit 1
fi
oms_wifi_address=$(ipconfig getifaddr en0)
if [[ -z "$oms_wifi_address" ]]; then
  print 'No Wi-Fi address found on en0. Connect Wi-Fi, or use python serve.py --host YOUR_PRIVATE_IP.'
  exit 1
fi
print "Staff link: http://${oms_wifi_address}:5055"
print 'Keep this window and computer running. Use only your trusted work Wi-Fi.'
exec .venv/bin/python serve.py --host "$oms_wifi_address"
