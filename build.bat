pyinstaller --additional-hooks-dir=. vizalerts.py
pushd .\dist\vizalerts\
mkdir twilio
mkdir twilio\conf
mkdir config
popd
cp .\config\cacert.pem .\dist\vizalerts\twilio\conf
cp .\config\vizalerts.yaml .\dist\vizalerts\config