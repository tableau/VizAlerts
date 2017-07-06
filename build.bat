pyinstaller --additional-hooks-dir=. --hidden-import=Queue vizalerts.py --onedir
pushd .\dist\vizalerts
mkdir twilio
mkdir twilio\conf
mkdir config
popd
copy .\version_history.txt .\dist\vizalerts
copy .\config\cacert.pem .\dist\vizalerts\twilio\conf
copy .\config\vizalerts.yaml .\dist\vizalerts\config
copy .\config\VizAlertsConfig.twb .\dist\vizalerts\config