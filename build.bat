del .\dist\*.* /F /Q
pyinstaller --additional-hooks-dir=. --hidden-import=Queue --noconfirm vizalerts.py --onefile --clean
mkdir .\dist\vizalerts
pushd .\dist\vizalerts
mkdir twilio
mkdir twilio\conf
mkdir config
mkdir docs
mkdir docs\media
mkdir demo
mkdir tests
mkdir logs
mkdir ops
mkdir vizalert
mkdir tabUtil
mkdir temp
popd

copy .\config\* .\dist\vizalerts\config
copy .\docs\* .\dist\vizalerts\docs
copy .\docs\media\* .\dist\vizalerts\docs\media
copy .\demo\* .\dist\vizalerts\demo
copy .\tests\* .\dist\vizalerts\tests
copy .\logs\* .\dist\vizalerts\logs
copy .\ops\* .\dist\vizalerts\ops
copy .\vizalert\* .\dist\vizalerts\vizalert
copy .\tabutil\* .\dist\vizalerts\tabUtil
copy .\temp\* .\dist\vizalerts\temp
copy .\tests\* .\dist\vizalerts\tests

copy .\version_history.txt .\dist\vizalerts
copy .\LICENSE .\dist\vizalerts
copy .\README.md .\dist\vizalerts
copy .\vizalerts.py .\dist\vizalerts

pandoc .\docs\install_guide.md -f markdown -t html -o  .\dist\vizalerts\docs\install_guide.html
pandoc .\docs\user_guide.md -f markdown -t html -o .\dist\vizalerts\docs\user_guide.html

copy .\dist\vizalerts.exe .\dist\vizalerts

7z a -r .\dist\vizalerts.zip .\dist\vizalerts\*